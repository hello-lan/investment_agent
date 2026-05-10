import uuid
from datetime import datetime
from fastapi import APIRouter
from ..db import get_db

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.get("")
async def list_sessions():
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, agent_id, title, status, created_at FROM sessions ORDER BY created_at DESC LIMIT 50"
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


@router.get("/{session_id}")
async def get_session(session_id: str):
    async with get_db() as db:
        cursor = await db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        session = await cursor.fetchone()
        if not session:
            return {"error": "Session not found"}
        cursor = await db.execute(
            "SELECT id, role, content, tool_calls, token_usage, created_at FROM messages WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        )
        messages = await cursor.fetchall()
    return {
        "session": dict(session),
        "messages": [dict(m) for m in messages],
    }


@router.delete("/{session_id}")
async def delete_session(session_id: str):
    async with get_db() as db:
        await db.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        await db.commit()
    return {"success": True}
