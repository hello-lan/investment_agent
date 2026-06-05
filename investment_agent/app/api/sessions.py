"""会话 API 路由 — 薄层，委托 SessionService 处理业务逻辑。"""

from fastapi import APIRouter, HTTPException

from ..services.session_service import SessionService

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


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


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    """删除会话及其关联消息"""
    await SessionService.delete_session(session_id)
    return {"success": True}
