"""AgentRunner — Agent 完整生命周期的封装入口。

FastAPI 层只需引入此类，注入依赖后调用 start() / run() / save_response() / cleanup()。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import AsyncGenerator, ClassVar

from .config import AgentRunConfig
from .context.manager import ContextManager, ContextResult
from .context.runtime_trimmer import get_runtime_trimmer
from .core.engine import AgentEngine
from .protocols import ExecutionLoop, LifecycleHooks, Storage
from .tools.registry import AUTO_BOUND_TOOLS, get_schemas_for_names, get_tool


class AgentRunner:
    """封装 Agent 完整生命周期：创建 → 执行 → 持久化 → 清理。

    依赖（构造注入）:
        storage:  持久化实现 (Storage 协议)
        execution: LLM 执行策略，默认 DualLoopEngine
        context:   上下文管理策略，默认 TokenBudgetManager
    """

    _engines: ClassVar[dict[str, AgentEngine]] = {}

    def __init__(
        self,
        storage: Storage,
        execution: ExecutionLoop | None = None,
        context: ContextManager | None = None,
    ):
        self._storage = storage
        self._execution = execution
        self._context = context
        # 运行时状态
        self._config: AgentRunConfig | None = None
        self._context_result: ContextResult | None = None
        self._assistant_content: str = ""

    # ── Public API ────────────────────────────────────────────────────────

    async def start(
        self,
        session_id: str,
        config: AgentRunConfig,
        message: str,
    ) -> tuple[str, str]:
        """准备对话：创建会话、保存用户消息、创建引擎、注册工具。

        Returns:
            (task_id, session_id)
        """
        self._config = config

        # 1. 创建或复用会话
        await self._storage.create_or_get_session(
            session_id=session_id,
            agent_id=config.agent_id,
            title=message,
        )

        # 2. 保存用户消息
        await self._storage.save_user_message(session_id, message)

        # 3. 创建引擎（含工具/技能注册）
        engine = self._create_engine(config, session_id)

        self._engines[engine.task_id] = engine
        return engine.task_id, session_id

    async def setup(
        self,
        session_id: str,
        config: AgentRunConfig,
    ) -> tuple[str, str]:
        """准备重试对话：复用已有会话（不重复保存用户消息），创建新引擎。

        与 start() 相同但跳过 save_user_message()，因为用户消息已在 DB 中。
        """
        self._config = config

        # 1. 复用已有会话
        await self._storage.create_or_get_session(
            session_id=session_id,
            agent_id=config.agent_id,
            title="",  # 重试时不更新标题
        )

        # 2. 创建引擎（含工具/技能注册）
        engine = self._create_engine(config, session_id)

        self._engines[engine.task_id] = engine
        return engine.task_id, session_id

    async def prepare_context(
        self,
        task_id: str,
        *,
        hooks: LifecycleHooks | None = None,
    ) -> list[dict]:
        """准备上下文：加载历史消息、运行上下文管理、应用到引擎。

        从 run() 中提取的前半部分，供 TaskManager 调用。
        返回准备好的消息列表。
        """
        engine = self._engines.get(task_id)
        if not engine:
            return []

        # 0. 填充 hooks 的 session_id / agent_name
        if hooks:
            hooks.session_id = getattr(hooks, "session_id", "") or engine.session_id
            if self._config and hasattr(hooks, "agent_name"):
                hooks.agent_name = hooks.agent_name or self._config.agent_name

        # 1. 加载历史消息
        messages = await self._storage.load_messages(engine.session_id)

        # 2. 上下文管理
        context_mgr = self._context or ContextManager(
            self._config.context if self._config else {},
            provider_type=getattr(engine.provider, "provider_type", "anthropic"),
            model_name=getattr(engine.provider, "model", "unknown"),
        )
        existing_summary = await self._storage.load_summary(engine.session_id)

        result = await context_mgr.prepare(
            system_prompt=engine.system_prompt,
            tools=engine.tools,
            messages=messages,
            provider=engine.provider,
            existing_summary=existing_summary,
        )
        self._context_result = result

        # 应用上下文管理结果
        engine.system_prompt = result.system_prompt
        if "tools_reduced" in result.warnings:
            engine.tools = result.tools
            kept_names = {t["name"] for t in result.tools}
            for name in list(engine.tool_handlers):
                if name not in kept_names:
                    del engine.tool_handlers[name]

        # 3. 触发 context_budget hook
        if hooks and hasattr(hooks, "on_context_budget"):
            await hooks.on_context_budget(result)

        return result.messages

    async def run(
        self,
        task_id: str,
        *,
        hooks: LifecycleHooks | None = None,
    ) -> AsyncGenerator[dict, None]:
        """执行 Agent 循环，逐事件 yield SSE 字典。

        内部处理:
        - 从 Storage 加载历史消息
        - 上下文预算管理（ContextManager）
        - 调用 ExecutionLoop.run()
        - 触发 LifecycleHooks 回调

        调用方在生成器耗尽后应依次调用 save_response() 和 cleanup()。
        """
        engine = self._engines.get(task_id)
        if not engine:
            yield {"type": "error", "message": "Task not found"}
            return

        # 0. 填充 hooks 的 session_id / agent_name
        if hooks:
            hooks.session_id = getattr(hooks, "session_id", "") or engine.session_id
            if self._config and hasattr(hooks, "agent_name"):
                hooks.agent_name = hooks.agent_name or self._config.agent_name

        # 1. 加载历史消息
        messages = await self._storage.load_messages(engine.session_id)

        # 2. 上下文管理
        context_mgr = self._context or ContextManager(
            self._config.context if self._config else {},
            provider_type=getattr(engine.provider, "provider_type", "anthropic"),
            model_name=getattr(engine.provider, "model", "unknown"),
        )
        existing_summary = await self._storage.load_summary(engine.session_id)

        result = await context_mgr.prepare(
            system_prompt=engine.system_prompt,
            tools=engine.tools,
            messages=messages,
            provider=engine.provider,
            existing_summary=existing_summary,
        )
        self._context_result = result

        # 应用上下文管理结果
        engine.system_prompt = result.system_prompt
        if "tools_reduced" in result.warnings:
            engine.tools = result.tools
            kept_names = {t["name"] for t in result.tools}
            for name in list(engine.tool_handlers):
                if name not in kept_names:
                    del engine.tool_handlers[name]

        # 3. 触发 context_budget hook
        if hooks and hasattr(hooks, "on_context_budget"):
            await hooks.on_context_budget(result)

        # 4. 执行循环
        assistant_content = ""
        last_step = 0
        cost_logged = False

        try:
            async for event in engine.run(result.messages):
                event_type = event.get("type", "unknown")
                step = event.get("step")
                if isinstance(step, int):
                    last_step = step

                # 每个事件触发 trace hook
                if hooks and hasattr(hooks, "on_event"):
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
                            "tool": event.get("tool"),
                            "input": event.get("input"),
                        }
                    elif event_type.startswith("sub_") and "tool_result" in event_type:
                        trace_detail = {
                            "delegate_id": event.get("delegate_id"),
                            "depth": event.get("depth"),
                            "tool": event.get("tool"),
                            "output": str(event.get("output", ""))[:500],
                            "duration_ms": event.get("duration_ms"),
                        }
                    elif event_type == "done":
                        trace_detail = {"usage": event.get("usage")}
                    elif event_type == "error":
                        trace_detail = {"message": event.get("message")}
                        if event.get("recent_tool_calls"):
                            trace_detail["recent_tool_calls"] = event["recent_tool_calls"]
                    elif event_type == "slow_think":
                        trace_detail = {"message": event.get("message") or event.get("content")}
                    await hooks.on_event(last_step or None, event_type, trace_detail)

                # 累积文本
                if event_type == "text_delta":
                    assistant_content += event["content"]

                # 终端事件 → cost + cache hooks
                elif event_type in ("done", "error", "interrupted") and not cost_logged:
                    usage = event.get("usage", {})
                    input_tokens = usage.get("input_tokens", engine.total_input_tokens)
                    output_tokens = usage.get("output_tokens", engine.total_output_tokens)
                    if hooks and hasattr(hooks, "on_cost"):
                        input_price = getattr(engine.provider, "_input_price", None)
                        output_price = getattr(engine.provider, "_output_price", None)
                        currency = getattr(engine.provider, "_currency", "USD")
                        await hooks.on_cost(
                            getattr(engine.provider, "model", "unknown"),
                            input_tokens, output_tokens,
                            input_price=input_price, output_price=output_price,
                            currency=currency,
                        )
                    if hooks and hasattr(hooks, "on_cache_metrics"):
                        if engine.total_cache_read_tokens or engine.total_cache_creation_tokens:
                            await hooks.on_cache_metrics(
                                last_step or None,
                                engine.total_cache_read_tokens,
                                engine.total_cache_creation_tokens,
                            )
                    cost_logged = True

                yield event

        finally:
            self._assistant_content = assistant_content

    async def save_response(self) -> str:
        """持久化 assistant 回复和摘要到 DB。必须在 run() 完成后调用。"""
        engine = None
        # 找到任一活跃引擎获取 session_id（通常只有一个）
        for eng in self._engines.values():
            engine = eng
            break

        if not engine:
            return ""

        session_id = engine.session_id
        msg_id = ""

        if self._assistant_content:
            msg_id = await self._storage.save_assistant_message(
                session_id, self._assistant_content,
            )

        # 保存摘要
        result = self._context_result
        if result and result.did_summarize and result.new_summary:
            await self._storage.save_summary(
                session_id=session_id,
                summary=result.new_summary,
                through_message_id=msg_id or "",
                token_count=result.summary_tokens,
            )

        return msg_id

    def cleanup(self, task_id: str) -> None:
        """移除引擎，释放内存。"""
        self._engines.pop(task_id, None)

    @classmethod
    def interrupt(cls, task_id: str) -> bool:
        """中断指定任务的 Agent 执行。"""
        engine = cls._engines.get(task_id)
        if engine:
            engine.interrupt()
            return True
        return False

    # ── Internal helpers ──────────────────────────────────────────────────

    def _create_engine(self, config: AgentRunConfig, session_id: str) -> AgentEngine:
        """创建引擎并注册工具/技能。start() 和 setup() 共用。"""
        runtime_trimmer = get_runtime_trimmer(
            config.runtime_trim_strategy, config.tool_trim_limits,
        )
        engine = AgentEngine(
            session_id=session_id,
            system_prompt=config.system_prompt,
            provider=config.provider,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            max_steps=config.max_steps,
            slow_think_interval=config.slow_think_interval,
            token_budget=config.token_budget,
            loop_detection_threshold=config.loop_detection_threshold,
            context_trim_interval=config.context_trim_interval,
            tool_trim_limits=config.tool_trim_limits,
            runtime_trimmer=runtime_trimmer,
            max_subagent_depth=config.max_subagent_depth,
            max_concurrent_subagents=config.max_concurrent_subagents,
            sub_agent_mode=config.sub_agent_mode,
        )
        allowed_tools = AUTO_BOUND_TOOLS | set(config.tools)
        for tool_schema in get_schemas_for_names(allowed_tools):
            tool = get_tool(tool_schema["name"])
            if tool:
                engine.register_tool(tool_schema, tool.run)
        if config.skills:
            from .skills.loader import get_skill
            for name in config.skills:
                skill = get_skill(name)
                if skill:
                    engine.register_skill(skill)
        return engine

    @classmethod
    def _get_session_id(cls, task_id: str) -> str | None:
        engine = cls._engines.get(task_id)
        return engine.session_id if engine else None
