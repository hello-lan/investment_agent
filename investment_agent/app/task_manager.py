"""TaskManager — 后台任务执行管理，与 SSE 连接解耦。

将引擎执行从 SSE 流中解耦出来，支持：
- 引擎在后台独立运行（asyncio.create_task），不受客户端断开影响
- 事件缓冲，支持断开重连后回放
- 多个 SSE 客户端可同时订阅同一任务
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, AsyncGenerator

from ..agent.runner import AgentRunner
from ..agent.core.engine import AgentEngine
from ..agent.core.events import build_trace_detail
from .observability.hooks_impl import ObservabilityHooks
from .observability.cost_tracker import _estimate_cost_usd

logger = logging.getLogger(__name__)


# 渲染事件类型：这些事件需要缓冲用于重连回放
_RENDER_EVENTS = frozenset({
    "text_delta", "tool_call", "tool_result",
    "slow_think", "done", "error", "interrupted",
})

# 任务完成后缓冲保留时间（秒）
_CLEANUP_DELAY = 600


class _TaskState:
    """单个后台任务的运行时状态。"""

    __slots__ = (
        "task_id", "session_id", "engine", "runner", "config",
        "buffer", "subscribers", "status", "done",
        "accumulated_text", "asyncio_task", "last_step",
    )

    def __init__(
        self,
        task_id: str,
        session_id: str,
        engine: AgentEngine,
        runner: AgentRunner,
        config: Any,
    ):
        self.task_id = task_id
        self.session_id = session_id
        self.engine = engine
        self.runner = runner
        self.config = config
        self.buffer: list[dict] = []
        self.subscribers: set[asyncio.Queue] = set()
        self.status: str = "running"  # running | done | error
        self.done: bool = False
        self.accumulated_text: str = ""
        self.asyncio_task: asyncio.Task | None = None
        self.last_step: int = 0


class TaskManager:
    """后台任务执行管理器（单例模式）。"""

    def __init__(self):
        self._tasks: dict[str, _TaskState] = {}
        self._lock = asyncio.Lock()

    async def start_task(
        self,
        task_id: str,
        engine: AgentEngine,
        runner: AgentRunner,
        config: Any,
        session_id: str,
    ) -> None:
        """启动后台任务执行。

        先同步更新 DB 会话状态为 running（确保前端 loadSessions 能看到转圈），
        再将引擎执行放入 asyncio.create_task 后台运行。
        """
        if task_id in self._tasks:
            logger.warning("Task %s already started, skipping", task_id)
            return

        state = _TaskState(task_id, session_id, engine, runner, config)
        self._tasks[task_id] = state

        # 关键：在返回前同步更新 DB，确保 HTTP 响应发出时 status 已是 'running'
        try:
            await runner.storage.update_session_task(
                session_id, status="running", task_id=task_id,
            )
        except Exception:
            logger.exception("Failed to update session status to running")

        state.asyncio_task = asyncio.create_task(self._run_task(state))

    async def _run_task(self, state: _TaskState) -> None:
        """后台任务编排：创建 hooks → 执行引擎循环 → 清理资源。"""
        hooks = ObservabilityHooks(
            task_id=state.task_id,
            session_id=state.session_id,
            agent_name=getattr(state.config, "agent_name", None),
        )

        try:
            await self._execute_engine_loop(state, hooks)
        except asyncio.CancelledError:
            logger.info("Task %s was cancelled", state.task_id)
            state.status = "error"
        except Exception as e:
            logger.exception("Task %s failed with exception", state.task_id)
            await self._broadcast(state, {"type": "error", "message": str(e)})
            state.status = "error"
        finally:
            await self._finalize_task(state)

    async def _execute_engine_loop(
        self, state: _TaskState, hooks: ObservabilityHooks,
    ) -> None:
        """准备上下文 + 驱动引擎循环，处理事件广播和 hook 触发。"""
        # 1. 准备上下文
        messages = await state.runner.prepare_context(state.task_id, hooks=hooks)
        if not messages:
            await self._broadcast(
                state, {"type": "error", "message": "Task not found or preparation failed"},
            )
            state.status = "error"
            state.done = True
            return

        # 2. 执行引擎循环
        cost_logged = False
        async for event in state.engine.run(messages):
            event_type = event.get("type", "unknown")
            step = event.get("step")
            if isinstance(step, int):
                state.last_step = step

            # 触发 trace hook
            await self._fire_event_hook(hooks, state.last_step, event_type, event)

            # 累积文本
            if event_type == "text_delta":
                state.accumulated_text += event["content"]

            # 终端事件 → cost + cache hooks + 更新会话统计
            if event_type in ("done", "error", "interrupted") and not cost_logged:
                await self._fire_terminal_hooks(hooks, state.engine, state.last_step, event)
                cost_info = await self._update_session_usage(state, event)
                cost_logged = True
                # 将 cost + cache 信息注入终端事件，前端可据此更新用量面板
                if cost_info and event_type == "done":
                    event["cost"] = cost_info["cost"]
                    event["currency"] = cost_info["currency"]
                    event["cache_read_tokens"] = cost_info["cache_read_tokens"]
                    event["cache_creation_tokens"] = cost_info["cache_creation_tokens"]

            # 缓冲渲染事件并广播给订阅者（包括子Agent事件）
            if event_type in _RENDER_EVENTS or event_type.startswith("sub_"):
                await self._broadcast(state, event)

            if event_type == "error":
                state.status = "error"
            elif event_type in ("done", "interrupted"):
                state.status = "done"

    async def _finalize_task(self, state: _TaskState) -> None:
        """任务收尾：保存回复、清理引擎、恢复会话状态、调度延迟清理。"""
        state.done = True
        task_id = state.task_id
        session_id = state.session_id

        # 保存 assistant 回复 —— 必须在 cleanup 之前执行
        try:
            state.runner.set_assistant_content(state.accumulated_text)
            await self._safe_save_response(state)
        except Exception:
            logger.exception("Failed to save response for task %s", task_id)

        # 清理引擎（从 _engines 中移除）
        try:
            state.runner.cleanup(task_id)
        except Exception:
            logger.exception("Failed to cleanup engine for task %s", task_id)

        # 恢复会话状态：正常完成恢复 active，出错保持 error
        final_status = "active" if state.status == "done" else state.status
        try:
            await state.runner.storage.update_session_task(
                session_id, status=final_status, task_id=None,
            )
        except Exception:
            logger.exception("Failed to update session status after task completion")

        # 延迟清理缓冲
        asyncio.create_task(self._cleanup_later(task_id))

    async def _safe_save_response(self, state: _TaskState) -> None:
        """安全保存 assistant 回复：直接使用 state 中的信息，不依赖 _engines 查找。

        原 save_response() 通过遍历 _engines 获取 session_id，
        但引擎可能已被 cleanup 或因取消而不可用。此方法直接使用 state 中保存的信息。
        """
        if not state.accumulated_text:
            return

        msg_id = await state.runner.storage.save_assistant_message(
            state.session_id, state.accumulated_text,
        )

    async def _broadcast(self, state: _TaskState, event: dict) -> None:
        """将事件加入缓冲并推送给所有订阅者。"""
        async with self._lock:
            state.buffer.append(event)
            for q in state.subscribers:
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    pass  # 丢弃：订阅者消费太慢

    async def _fire_event_hook(
        self, hooks: ObservabilityHooks, step: int, event_type: str, event: dict,
    ) -> None:
        """触发 on_event hook。"""
        trace_detail = build_trace_detail(event_type, event)
        try:
            await hooks.on_event(step or None, event_type, trace_detail)
        except Exception:
            logger.debug("on_event hook failed", exc_info=True)

    async def _fire_terminal_hooks(
        self,
        hooks: ObservabilityHooks,
        engine: AgentEngine,
        last_step: int,
        event: dict,
    ) -> None:
        """触发 on_cost 和 on_cache_metrics hooks。"""
        usage = event.get("usage", {})
        input_tokens = usage.get("input_tokens", engine.total_input_tokens)
        output_tokens = usage.get("output_tokens", engine.total_output_tokens)
        cache_read = engine.total_cache_read_tokens
        cache_create = engine.total_cache_creation_tokens

        try:
            if hasattr(hooks, "on_cost"):
                await hooks.on_cost(
                    getattr(engine.provider, "model", "unknown"),
                    input_tokens, output_tokens,
                    input_price=engine.provider.input_price,
                    output_price=engine.provider.output_price,
                    currency=engine.provider.currency,
                    cache_read_tokens=cache_read,
                    cache_creation_tokens=cache_create,
                    cache_read_price=engine.provider.cache_read_price,
                    cache_creation_price=engine.provider.cache_creation_price,
                )
        except Exception:
            logger.debug("on_cost hook failed", exc_info=True)

        # 缓存命中率诊断
        total_cacheable = input_tokens + cache_read + cache_create
        hit_ratio = cache_read / total_cacheable if total_cacheable > 0 else 0
        provider_type = getattr(engine.provider, "provider_type", "")
        if provider_type == "anthropic" and cache_read == 0 and input_tokens > 5000:
            logger.warning(
                "Zero cache hits for anthropic provider (input=%d tokens). "
                "System prompt may not be stable — check for dynamic content.",
                input_tokens,
            )

        try:
            if hasattr(hooks, "on_cache_metrics"):
                if cache_read or cache_create:
                    await hooks.on_cache_metrics(last_step or None, cache_read, cache_create)
        except Exception:
            logger.debug("on_cache_metrics hook failed", exc_info=True)

    async def _update_session_usage(self, state: _TaskState, event: dict) -> dict | None:
        """将本次任务的 token 用量累加到 sessions 表。返回 cost 信息用于注入前端事件。"""
        usage = event.get("usage", {})
        input_tokens = usage.get("input_tokens", state.engine.total_input_tokens)
        output_tokens = usage.get("output_tokens", state.engine.total_output_tokens)
        if not input_tokens and not output_tokens:
            return None

        cache_read = state.engine.total_cache_read_tokens
        cache_create = state.engine.total_cache_creation_tokens
        currency = state.engine.provider.currency or "USD"

        cost_usd = _estimate_cost_usd(
            input_tokens, output_tokens,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_create,
            input_price=state.engine.provider.input_price,
            output_price=state.engine.provider.output_price,
            cache_read_price=state.engine.provider.cache_read_price,
            cache_creation_price=state.engine.provider.cache_creation_price,
        ) or 0

        try:
            await state.runner.storage.update_session_usage(
                state.session_id,
                input_tokens=int(input_tokens),
                output_tokens=int(output_tokens),
                cost_usd=float(cost_usd),
                cache_read_tokens=int(cache_read),
                cache_creation_tokens=int(cache_create),
                currency=currency,
            )
        except Exception:
            logger.debug("update_session_usage failed for task %s", state.task_id, exc_info=True)

        return {
            "cost": cost_usd,
            "currency": currency,
            "cache_read_tokens": cache_read,
            "cache_creation_tokens": cache_create,
        }

    async def _cleanup_later(self, task_id: str) -> None:
        """延迟清理任务状态和缓冲。"""
        try:
            await asyncio.sleep(_CLEANUP_DELAY)
            self._tasks.pop(task_id, None)
        except asyncio.CancelledError:
            pass

    # ── 公共 API ──────────────────────────────────────────────────────

    async def stream_events(self, task_id: str) -> AsyncGenerator[dict, None]:
        """订阅任务事件流：先回放缓冲，再实时推送。

        用于 SSE 端点。客户端断开时自动从订阅者中移除。
        """
        state = self._tasks.get(task_id)
        if not state:
            yield {"type": "error", "message": "Task not found"}
            return

        # 如果任务已完成，直接回放缓冲
        if state.done:
            for event in state.buffer:
                yield event
            return

        # 订阅：在锁保护下加入队列并快照缓冲，确保不遗漏事件
        queue: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            state.subscribers.add(queue)
            buffer_snapshot = list(state.buffer)

        try:
            # 回放已有缓冲
            for event in buffer_snapshot:
                yield event

            # 实时推送
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    yield event
                    # 终端事件后退出
                    if event.get("type") in ("done", "error", "interrupted"):
                        break
                except asyncio.TimeoutError:
                    # 心跳检查：任务是否还在
                    if state.done:
                        # 回放可能遗漏的最终事件
                        for ev in state.buffer[len(buffer_snapshot):]:
                            yield ev
                        break
                    # 发送心跳保持 SSE 连接
                    yield {"type": "_ping"}
        finally:
            async with self._lock:
                state.subscribers.discard(queue)

    def is_running(self, task_id: str) -> bool:
        """检查任务是否正在运行。"""
        state = self._tasks.get(task_id)
        return state is not None and not state.done

    def get_session_id(self, task_id: str) -> str | None:
        """获取任务关联的 session_id。"""
        state = self._tasks.get(task_id)
        return state.session_id if state else None


# 模块级单例
task_manager = TaskManager()
