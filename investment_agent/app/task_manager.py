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
from .observability.hooks_impl import ObservabilityHooks

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
        from .db import get_db
        try:
            async with get_db() as db:
                await db.execute(
                    "UPDATE sessions SET status = 'running', current_task_id = ? WHERE id = ?",
                    (task_id, session_id),
                )
                await db.commit()
        except Exception:
            logger.exception("Failed to update session status to running")

        state.asyncio_task = asyncio.create_task(self._run_task(state))

    async def _run_task(self, state: _TaskState) -> None:
        """后台任务：执行引擎循环，缓冲事件，管理会话状态。"""
        from .db import get_db

        task_id = state.task_id
        session_id = state.session_id

        # 创建可观测性 hooks
        hooks = ObservabilityHooks(
            task_id=task_id,
            session_id=session_id,
            agent_name=getattr(state.config, "agent_name", None),
        )

        cost_logged = False
        final_status = "active"

        try:
            # 1. 准备上下文
            messages = await state.runner.prepare_context(task_id, hooks=hooks)
            if not messages:
                await self._broadcast(state, {"type": "error", "message": "Task not found or preparation failed"})
                state.status = "error"
                state.done = True
                return

            # 2. 执行引擎循环
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

                # 终端事件 → cost + cache hooks
                if event_type in ("done", "error", "interrupted") and not cost_logged:
                    await self._fire_terminal_hooks(hooks, state.engine, state.last_step, event)
                    cost_logged = True

                # 缓冲渲染事件并广播给订阅者（包括子Agent事件）
                if event_type in _RENDER_EVENTS or event_type.startswith("sub_"):
                    await self._broadcast(state, event)

                if event_type == "error":
                    state.status = "error"
                elif event_type in ("done", "interrupted"):
                    state.status = "done"

        except asyncio.CancelledError:
            logger.info("Task %s was cancelled", task_id)
            state.status = "error"
        except Exception as e:
            logger.exception("Task %s failed with exception", task_id)
            await self._broadcast(state, {"type": "error", "message": str(e)})
            state.status = "error"
        finally:
            state.done = True

            # 保存 assistant 回复 —— 必须在 cleanup 之前执行，
            # 因为 save_response() 需要从 _engines 获取 session_id
            try:
                state.runner._assistant_content = state.accumulated_text
                await self._safe_save_response(state)
            except Exception:
                logger.exception("Failed to save response for task %s", task_id)

            # 清理引擎（从 _engines 中移除）
            try:
                state.runner.cleanup(task_id)
            except Exception:
                logger.exception("Failed to cleanup engine for task %s", task_id)

            # 恢复会话状态
            try:
                async with get_db() as db:
                    await db.execute(
                        "UPDATE sessions SET status = ?, current_task_id = NULL WHERE id = ?",
                        (final_status, session_id),
                    )
                    await db.commit()
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

        msg_id = await state.runner._storage.save_assistant_message(
            state.session_id, state.accumulated_text,
        )

        # 保存摘要（如果有上下文管理结果）
        result = state.runner._context_result
        if result and result.did_summarize and result.new_summary:
            try:
                await state.runner._storage.save_summary(
                    session_id=state.session_id,
                    summary=result.new_summary,
                    through_message_id=msg_id,
                    token_count=result.summary_tokens,
                )
            except Exception:
                logger.debug("Failed to save summary for task %s", state.task_id, exc_info=True)

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
        """触发 on_event hook（与原 runner.run() 逻辑一致）。"""
        trace_detail: dict | None = None
        if event_type == "llm_request":
            trace_detail = {"messages": event.get("messages")}
        elif event_type == "llm_response":
            trace_detail = {
                "input_tokens": event.get("input_tokens"),
                "output_tokens": event.get("output_tokens"),
                "cache_read_tokens": event.get("cache_read_tokens"),
                "cache_creation_tokens": event.get("cache_creation_tokens"),
                "content": event.get("content"),
                "reasoning": event.get("reasoning"),
                "tool_calls": event.get("tool_calls"),
            }
        elif event_type == "tool_call":
            trace_detail = {"tool": event.get("tool"), "input": event.get("input")}
        elif event_type == "tool_result":
            trace_detail = {
                "tool": event.get("tool"),
                "output": str(event.get("output", ""))[:500],
                "duration_ms": event.get("duration_ms"),
            }
        elif event_type.startswith("sub_") and "tool_call" in event_type:
            trace_detail = {
                "delegate_id": event.get("delegate_id"),
                "depth": event.get("depth"),
                "agent_type": event.get("agent_type"),
                "tool": event.get("tool"),
                "input": event.get("input"),
            }
        elif event_type.startswith("sub_") and "tool_result" in event_type:
            trace_detail = {
                "delegate_id": event.get("delegate_id"),
                "depth": event.get("depth"),
                "agent_type": event.get("agent_type"),
                "tool": event.get("tool"),
                "output": str(event.get("output", ""))[:500],
                "duration_ms": event.get("duration_ms"),
            }
        elif event_type.startswith("sub_") and "llm_request" in event_type:
            trace_detail = {
                "delegate_id": event.get("delegate_id"),
                "depth": event.get("depth"),
                "agent_type": event.get("agent_type"),
                "step": event.get("step"),
                "messages": event.get("messages"),
            }
        elif event_type.startswith("sub_") and "llm_response" in event_type:
            trace_detail = {
                "delegate_id": event.get("delegate_id"),
                "depth": event.get("depth"),
                "agent_type": event.get("agent_type"),
                "step": event.get("step"),
                "input_tokens": event.get("input_tokens"),
                "output_tokens": event.get("output_tokens"),
                "cache_read_tokens": event.get("cache_read_tokens"),
                "cache_creation_tokens": event.get("cache_creation_tokens"),
                "content": event.get("content"),
                "reasoning": event.get("reasoning"),
                "tool_calls": event.get("tool_calls"),
            }
        elif event_type == "done":
            trace_detail = {"usage": event.get("usage")}
        elif event_type == "error":
            trace_detail = {"message": event.get("message")}
            if event.get("recent_tool_calls"):
                trace_detail["recent_tool_calls"] = event["recent_tool_calls"]
        elif event_type == "slow_think":
            trace_detail = {"message": event.get("message") or event.get("content")}

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

        try:
            if hasattr(hooks, "on_cost"):
                input_price = getattr(engine.provider, "_input_price", None)
                output_price = getattr(engine.provider, "_output_price", None)
                currency = getattr(engine.provider, "_currency", "USD")
                await hooks.on_cost(
                    getattr(engine.provider, "model", "unknown"),
                    input_tokens, output_tokens,
                    input_price=input_price, output_price=output_price,
                    currency=currency,
                )
        except Exception:
            logger.debug("on_cost hook failed", exc_info=True)

        try:
            if hasattr(hooks, "on_cache_metrics"):
                if engine.total_cache_read_tokens or engine.total_cache_creation_tokens:
                    await hooks.on_cache_metrics(
                        last_step or None,
                        engine.total_cache_read_tokens,
                        engine.total_cache_creation_tokens,
                    )
        except Exception:
            logger.debug("on_cache_metrics hook failed", exc_info=True)

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
