"""AgentRunner — Agent 完整生命周期的封装入口。

FastAPI 层只需引入此类，注入依赖后调用 start() / setup() / prepare_context() / cleanup()。
"""

from __future__ import annotations

from typing import ClassVar

from .config import AgentRunConfig
from .context.manager import ContextManager, ContextResult
from .context.runtime_trimmer import get_runtime_trimmer
from .core.engine import AgentEngine
from .protocols import ExecutionLoop, LifecycleHooks, Storage
from .skills.dependency import expand_with_dependencies
from .tools.access_policy import AccessPolicy
from .tools.registry import AUTO_BOUND_TOOLS, get_schemas_for_names, get_tool
from .tools.run_command import RunCommandTool
from ..config import PROJECT_ROOT


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

        供 TaskManager 调用。返回准备好的消息列表。
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

    def cleanup(self, task_id: str) -> None:
        """移除引擎，释放内存。"""
        self._engines.pop(task_id, None)

    @classmethod
    def get_engine(cls, task_id: str) -> AgentEngine | None:
        """获取指定任务的引擎实例。"""
        return cls._engines.get(task_id)

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

        # 展开 orch 技能的 depends_on 依赖，供 AccessPolicy 和 prepare_delegate_task 使用
        all_skill_names = expand_with_dependencies(config.skills) if config.skills else []

        # 设置允许的技能名称集合（含依赖，供 prepare_delegate_task 委派到依赖技能）
        engine._allowed_skill_names = set(all_skill_names)

        # skills 为空时不注册 Skill 工具，LLM 看不到也就无法调用
        if not config.skills:
            allowed_tools = allowed_tools - {"Skill"}

        # run_command 单独注册独立实例 + AccessPolicy（不修改全局单例）
        allowed_tools = allowed_tools - {"run_command"}

        policy = AccessPolicy.for_agent(str(PROJECT_ROOT), all_skill_names)
        engine._system_prompt += policy.prompt_section()
        run_tool = RunCommandTool()
        run_tool.access_policy = policy
        engine.register_tool(run_tool.schema, run_tool.run)

        for tool_schema in get_schemas_for_names(allowed_tools):
            tool = get_tool(tool_schema["name"])
            if not tool:
                continue

            # Skill 工具加闭包过滤，只允许访问已启用的技能
            if tool.name == "Skill" and config.skills:
                allowed_names = set(config.skills)
                original_run = tool.run

                async def filtered_skill_run(
                    name, _orig=original_run, _allowed=allowed_names,
                ):
                    if name not in _allowed:
                        available = ", ".join(sorted(_allowed)) or "(无)"
                        return (
                            f"技能 '{name}' 不在当前Agent的启用列表中。"
                            f"可用技能: {available}"
                        )
                    return await _orig(name=name)

                engine.register_tool(tool_schema, filtered_skill_run)

            else:
                engine.register_tool(tool_schema, tool.run)

        if config.skills:
            from .skills.loader import get_skill
            for name in config.skills:
                skill = get_skill(name)
                if skill:
                    engine.register_skill(skill)
        return engine
