"""AgentRunner — Agent 完整生命周期的封装入口。

FastAPI 层只需引入此类，注入依赖后调用 start() / setup() / prepare_context() / cleanup()。
"""

from __future__ import annotations

import os
import shutil
from typing import ClassVar

from .config import AgentRunConfig, EngineConfig, OFFLOAD_AWARE_PROMPT
from .constants import ProviderType
from .context.context_offloader import ContextOffloader
from .context.manager import ContextManager, ContextResult
from .context.runtime_compressor import CompressRuntimeCompressor, NoOpRuntimeCompressor
from .core.engine import AgentEngine
from .protocols import ExecutionLoop, LifecycleHooks, Storage
from .registry_container import AgentRegistry
from .skills.dependency import expand_with_dependencies
from .tools.access_policy import AccessPolicy
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
            provider_type=getattr(engine.provider, "provider_type", ProviderType.ANTHROPIC),
            model_name=getattr(engine.provider, "model", "unknown"),
        )

        result = await context_mgr.prepare(
            system_prompt=engine.system_prompt,
            tools=engine.tools,
            messages=messages,
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

    @property
    def storage(self) -> Storage:
        """公开 Storage 实例，供 TaskManager 等外部组件使用。"""
        return self._storage

    @property
    def context_result(self) -> ContextResult | None:
        """获取上下文管理的结果（prepare_context 后可用）。"""
        return self._context_result

    def set_assistant_content(self, content: str) -> None:
        """设置 assistant 回复内容（由 TaskManager 在任务完成后调用）。"""
        self._assistant_content = content

    def cleanup(self, task_id: str) -> None:
        """移除引擎，释放内存，清理卸载临时文件。"""
        engine = self._engines.pop(task_id, None)
        # 清理上下文卸载临时文件
        session_id = engine.session_id if engine else task_id
        shutil.rmtree(
            os.path.join(PROJECT_ROOT, "data", ".offload", session_id),
            ignore_errors=True,
        )

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
        # 创建注册容器 + 编目默认工具
        registry = AgentRegistry()
        registry.bootstrap_default_tools()

        # 创建 offloader + trimmer
        needs_compressor = config.context_trim_token_threshold > 0
        if needs_compressor:
            offload_dir = os.path.join(PROJECT_ROOT, "data", ".offload", session_id)
            offloader = ContextOffloader(
                offload_dir,
                threshold=config.offload_threshold,
                summary_strategy=config.offload_summary_strategy,
                summary_chars=config.offload_summary_chars,
                provider=config.provider,
            )
            runtime_compressor = CompressRuntimeCompressor(
                offloader=offloader,
            )
        else:
            runtime_compressor = NoOpRuntimeCompressor()

        engine_cfg = EngineConfig(
            max_steps=config.max_steps,
            slow_think_interval=config.slow_think_interval,
            token_budget=config.token_budget,
            loop_detection_threshold=config.loop_detection_threshold,
            context_trim_token_threshold=config.context_trim_token_threshold,
            max_subagent_depth=config.max_subagent_depth,
            offload_threshold=config.offload_threshold,
            offload_summary_strategy=config.offload_summary_strategy,
            offload_summary_chars=config.offload_summary_chars,
            planning_max_tokens=config.planning_max_tokens,
        )
        engine = AgentEngine(
            session_id=session_id,
            system_prompt=config.system_prompt,
            provider=config.provider,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            config=engine_cfg,
            runtime_compressor=runtime_compressor,
        )
        allowed_tools = registry.auto_bound_tools | set(config.tools)

        # 展开 orch 技能的 depends_on 依赖，供 AccessPolicy 和 prepare_delegate_task 使用
        all_skill_names = expand_with_dependencies(config.skills) if config.skills else []

        # 设置允许的技能名称集合（含依赖，供 prepare_delegate_task 委派到依赖技能）
        engine._allowed_skill_names = set(all_skill_names)

        # skills 为空时不注册 Skill 工具，LLM 看不到也就无法调用
        if not config.skills:
            allowed_tools = allowed_tools - {"Skill"}

        # run_command 单独注册独立实例 + AccessPolicy（每个会话独立策略）
        allowed_tools = allowed_tools - {"run_command"}

        policy = AccessPolicy.for_agent(str(PROJECT_ROOT), all_skill_names)
        engine._system_prompt += policy.prompt_section()
        engine._system_prompt += OFFLOAD_AWARE_PROMPT
        from .tools.run_command import RunCommandTool  # 延迟导入避免循环依赖
        run_tool = RunCommandTool()
        run_tool.access_policy = policy
        engine.register_tool(run_tool.schema, run_tool.run)

        # 通过 registry 注册其他工具
        for tool_schema in registry.get_schemas_for_names(allowed_tools):
            tool = registry.get_tool(tool_schema["name"])
            if not tool:
                continue

            # Skill 工具加闭包过滤，只允许访问已启用的技能
            if tool.name == "Skill" and config.skills:
                from .skills.filtered_runner import make_filtered_skill_runner
                filtered_run = make_filtered_skill_runner(
                    set(all_skill_names), tool.run,
                )
                engine.register_tool(tool_schema, filtered_run)
            else:
                engine.register_tool(tool_schema, tool.run)

        # 技能加载（通过全局 loader，保持向后兼容）
        if config.skills:
            from .skills.loader import get_skill
            for name in config.skills:
                skill = get_skill(name)
                if skill:
                    engine.register_skill(skill)
        return engine
