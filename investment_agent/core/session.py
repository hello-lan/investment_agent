from .engine import AgentEngine
from .models import get_provider

_engines: dict[str, AgentEngine] = {}


async def create_engine(
    session_id: str,
    system_prompt: str = "",
    provider_name: str | None = None,
) -> AgentEngine:
    provider = await get_provider(provider_name)
    engine = AgentEngine(session_id=session_id, system_prompt=system_prompt, provider=provider)
    _engines[engine.task_id] = engine
    return engine


def get_engine(task_id: str) -> AgentEngine | None:
    return _engines.get(task_id)


def interrupt_engine(task_id: str) -> bool:
    engine = _engines.get(task_id)
    if engine:
        engine.interrupt()
        return True
    return False


def remove_engine(task_id: str) -> None:
    _engines.pop(task_id, None)
