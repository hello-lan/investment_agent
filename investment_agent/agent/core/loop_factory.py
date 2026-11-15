"""Loop engine 工厂：根据配置创建具体执行循环实现。"""

from ..constants import LoopMode
from ..config import EngineConfig
from ..context.runtime_compressor import RuntimeCompressor
from .base_loop import BaseLoopEngine
from .dual_loop import DualLoopEngine
from .plan_execute_loop import PlanExecuteLoopEngine
from .react_loop import ReactLoopEngine
from .react_subagent_loop import ReactSubagentLoopEngine
from .workflow_loop import WorkflowLoopEngine
from .provider import ModelProvider


_ENGINE_REGISTRY = {
    LoopMode.DUAL_LOOP: DualLoopEngine,
    LoopMode.REACT: ReactLoopEngine,
    # 兼容旧 react_subagent：映射到普通 ReAct（用户定义 Subagent 由挂载驱动）
    LoopMode.REACT_SUBAGENT: ReactLoopEngine,
    LoopMode.PLAN_EXECUTE: PlanExecuteLoopEngine,
    LoopMode.WORKFLOW: WorkflowLoopEngine,
}


def create_loop_engine(
    *,
    session_id: str,
    config: EngineConfig,
    system_prompt: str = "",
    provider: ModelProvider | None = None,
    temperature: float | None = None,
    max_single_turn_output_tokens: int | None = None,
    runtime_compressor: RuntimeCompressor | None = None,
    subagent_depth: int = 0,
) -> BaseLoopEngine:
    """根据 loop_mode 创建具体执行循环。"""
    raw_mode = config.loop_mode
    if raw_mode == "react_subagent":
        mode = LoopMode.REACT
    else:
        try:
            mode = LoopMode(raw_mode)
        except ValueError:
            mode = LoopMode.DUAL_LOOP

    engine_cls = _ENGINE_REGISTRY.get(mode, DualLoopEngine)
    return engine_cls(
        session_id=session_id,
        config=config,
        system_prompt=system_prompt,
        provider=provider,
        temperature=temperature,
        max_single_turn_output_tokens=max_single_turn_output_tokens,
        runtime_compressor=runtime_compressor,
        subagent_depth=subagent_depth,
    )
