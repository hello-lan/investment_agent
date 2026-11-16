"""会话服务层 — 封装 sessions 相关的所有 DB 操作。

从 app/api/sessions.py 提取，分离 HTTP 路由与数据访问逻辑。
"""

from __future__ import annotations

from ...agent.context.auxiliary_tasks import TITLE_MAX_CHARS, generate_session_title
from ..config_factory import get_utility_provider
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
                       s.input_tokens, s.output_tokens, s.cost_usd,
                       s.cache_read_tokens, s.cache_creation_tokens, s.currency,
                       s.context_mode, s.created_at,
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
    async def set_context_mode(session_id: str, mode: str) -> bool:
        """设置回放方式。会话不存在时返回 False。"""
        if mode not in ("chat", "full"):
            raise ValueError(mode)
        async with get_db() as db:
            cursor = await db.execute(
                "UPDATE sessions SET context_mode = ? WHERE id = ?",
                (mode, session_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    @staticmethod
    async def delete_session(session_id: str) -> None:
        """删除会话及其关联消息。"""
        async with get_db() as db:
            await db.execute(
                "DELETE FROM messages WHERE session_id = ?", (session_id,)
            )
            await db.execute(
                "DELETE FROM context_snapshots WHERE session_id = ?", (session_id,)
            )
            await db.execute(
                "DELETE FROM sessions WHERE id = ?", (session_id,)
            )
            await db.commit()

    @staticmethod
    async def generate_title(session_id: str) -> str:
        """读取本 session 全部用户消息，调用辅助模型生成标题并写回。

        Raises:
            LookupError: 会话不存在
            ValueError: 无用户消息，或未配置辅助模型
        """
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT id FROM sessions WHERE id = ?", (session_id,)
            )
            if not await cursor.fetchone():
                raise LookupError("Session not found")
            cursor = await db.execute(
                "SELECT content FROM messages "
                "WHERE session_id = ? AND role = 'user' ORDER BY created_at",
                (session_id,),
            )
            rows = await cursor.fetchall()

        texts = [r["content"] or "" for r in rows]
        if not any(t.strip() for t in texts):
            raise ValueError("没有可用于生成标题的用户消息")

        provider = await get_utility_provider()
        title = await generate_session_title(provider, texts)
        title = (title or "未命名")[:TITLE_MAX_CHARS]

        async with get_db() as db:
            await db.execute(
                "UPDATE sessions SET title = ? WHERE id = ?",
                (title, session_id),
            )
            await db.commit()
        return title
