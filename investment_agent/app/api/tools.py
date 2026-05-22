from fastapi import APIRouter

from ...agent.tools.registry import get_all_tool_infos

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("")
async def list_tools():
    return get_all_tool_infos()
