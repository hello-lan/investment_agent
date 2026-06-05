"""会话服务层 — 封装 sessions 相关的所有 DB 操作。

从 app/api/sessions.py 提取，分离 HTTP 路由与数据访问逻辑。
"""

from __future__ import annotations

from ..db import get_db


class SessionService:
    """会话管理：列表查询、详情获取、删除。"""

    @staticmethod
    async def list_sessions(limit: int = 50) -> list[dict]:
        """历史会话列表（最近 N 条），含首条用户消息预览。"""
        async with get_db() as db:
            cursor = await db.execute(
                """
                SELECT s.id, s.agent_id, s.title, s.status, s.current_task_id,
                       s.input_tokens, s.output_tokens, s.cost_usd, s.created_at,
                       (SELECT SUBSTR(content, 1, 50) FROM messages
                        WHERE session_id = s.id AND role = 'user'
                        ORDER BY created_at LIMIT 1) AS preview
                FROM sessions s
                ORDER BY s.created_at DESC LIMIT ?
                """,
                (limit,),
            )
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    async def get_session_with_messages(session_id: str) -> dict | None:
        """会话详情 + 全部消息记录。

        Returns:
            成功: {"session": dict, "messages": list[dict]}
            None: 会话不存在
        """
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            )
            session = await cursor.fetchone()
            if not session:
                return None

            cursor = await db.execute(
                "SELECT id, role, content, tool_calls, token_usage, created_at "
                "FROM messages WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            )
            messages = await cursor.fetchall()

        return {
            "session": dict(session),
            "messages": [dict(m) for m in messages],
        }

    @staticmethod
    async def delete_session(session_id: str) -> None:
        """删除会话及其关联消息。"""
        async with get_db() as db:
            await db.execute(
                "DELETE FROM messages WHERE session_id = ?", (session_id,)
            )
            await db.execute(
                "DELETE FROM sessions WHERE id = ?", (session_id,)
            )
            await db.commit()
