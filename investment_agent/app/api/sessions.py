"""会话 API 路由 — 薄层，委托 SessionService 处理业务逻辑。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.session_service import SessionService

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class ContextModeRequest(BaseModel):
    mode: str


@router.get("")
async def list_sessions():
    """历史会话列表（最近 50 条）"""
    return await SessionService.list_sessions()


@router.get("/{session_id}")
async def get_session(session_id: str):
    """会话详情 + 全部消息记录"""
    result = await SessionService.get_session_with_messages(session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return result


@router.patch("/{session_id}/context")
async def set_context_mode(session_id: str, body: ContextModeRequest):
    """切换会话的上下文回放方式：chat 可见对话，full 完整轨迹。"""
    if body.mode not in ("chat", "full"):
        raise HTTPException(status_code=400, detail="mode 只能是 chat 或 full")
    updated = await SessionService.set_context_mode(session_id, body.mode)
    if not updated:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"success": True, "context_mode": body.mode}


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """删除会话及其关联消息"""
    await SessionService.delete_session(session_id)
    return {"success": True}
