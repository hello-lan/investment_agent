from .engine import AgentEngine
from .models import get_provider

# 全局引擎字典：task_id → AgentEngine，实现并发任务隔离
_engines: dict[str, AgentEngine] = {}


async def create_engine(
    session_id: str,
    system_prompt: str = "",
    provider_name: str | None = None,
    engine_config: dict | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> AgentEngine:
    """为每次对话创建独立的 AgentEngine 实例"""
    provider = await get_provider(provider_name)
    engine = AgentEngine(
        session_id=session_id,
        system_prompt=system_prompt,
        provider=provider,
        engine_config=engine_config,
        temperature=temperature,
        max_tokens=max_tokens,
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
