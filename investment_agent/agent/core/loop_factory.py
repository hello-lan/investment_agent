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
    LoopMode.REACT_SUBAGENT: ReactSubagentLoopEngine,
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
    max_tokens: int | None = None,
    runtime_compressor: RuntimeCompressor | None = None,
    subagent_depth: int = 0,
) -> BaseLoopEngine:
    """根据 loop_mode 创建具体执行循环。"""
    try:
        mode = LoopMode(config.loop_mode)
    except ValueError:
        mode = LoopMode.DUAL_LOOP

    engine_cls = _ENGINE_REGISTRY.get(mode, DualLoopEngine)
    return engine_cls(
        session_id=session_id,
        config=config,
        system_prompt=system_prompt,
        provider=provider,
        temperature=temperature,
        max_tokens=max_tokens,
        runtime_compressor=runtime_compressor,
        subagent_depth=subagent_depth,
    )
