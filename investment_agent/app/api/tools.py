from fastapi import APIRouter

from ...agent.registry_container import AgentRegistry

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("")
async def list_tools():
    registry = AgentRegistry()
    registry.bootstrap_default_tools()
    return registry.get_all_tool_infos()
