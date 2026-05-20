from ...config import get_settings
from .engine import AgentEngine
from .models import ModelProvider

# 全局引擎字典：task_id → AgentEngine，实现并发任务隔离
_engines: dict[str, AgentEngine] = {}


def _resolve_engine_params(agent_cfg: dict | None) -> dict:
    """合并 agent 级 engine_config 与全局 settings，返回已解析的引擎参数。"""
    global_cfg = get_settings().get("engine", {})
    agent_cfg = agent_cfg or {}
    return {
        "max_steps": agent_cfg.get("max_steps") or global_cfg.get("max_steps", 30),
        "slow_think_interval": agent_cfg.get("slow_think_interval") or global_cfg.get("slow_think_interval", 3),
        "token_budget": agent_cfg.get("token_budget") or global_cfg.get("token_budget", 100000),
        "loop_detection_threshold": agent_cfg.get("loop_detection_threshold") or global_cfg.get("loop_detection_threshold", 3),
    }


async def create_engine(
    session_id: str,
    system_prompt: str = "",
    provider: ModelProvider | None = None,
    engine_config: dict | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> AgentEngine:
    """为每次对话创建独立的 AgentEngine 实例"""
    engine_params = _resolve_engine_params(engine_config)
    engine = AgentEngine(
        session_id=session_id,
        system_prompt=system_prompt,
        provider=provider,
        temperature=temperature,
        max_tokens=max_tokens,
        **engine_params,
    )
    _engines[engine.task_id] = engine
    return engine


def get_engine(task_id: str) -> AgentEngine | None:
    """根据 task_id 获取对应的引擎实例"""
    return _engines.get(task_id)


def interrupt_engine(task_id: str) -> bool:
    """中断指定任务的执行"""
    engine = _engines.get(task_id)
    if engine:
        engine.interrupt()
        return True
    return False


def remove_engine(task_id: str) -> None:
    """任务完成后清理引擎实例，释放内存"""
    _engines.pop(task_id, None)
