"""会话服务层 — 封装 sessions 相关的所有 DB 操作。

从 app/api/sessions.py 提取，分离 HTTP 路由与数据访问逻辑。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

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
                       s.context_mode, s.collaboration_mode, s.created_at,
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
    async def set_collaboration_mode(session_id: str, mode: str) -> bool:
        """设置协作模式。会话不存在时返回 False。"""
        if mode not in ("agent", "plan"):
            raise ValueError(mode)
        async with get_db() as db:
            cursor = await db.execute(
                "UPDATE sessions SET collaboration_mode = ? WHERE id = ?",
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
    async def fork_session_at_message(
        source_session_id: str, message_id: str,
    ) -> str:
        """在指定消息处分叉：新建会话并复制该节点及之前的全部消息。

        Returns:
            new_session_id

        Raises:
            LookupError: 源会话或消息不存在 / 消息不属于该会话
        """
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT id, agent_id, title, context_mode, collaboration_mode "
                "FROM sessions WHERE id = ?",
                (source_session_id,),
            )
            source = await cursor.fetchone()
            if not source:
                raise LookupError("Session not found")

            cursor = await db.execute(
                "SELECT id, created_at FROM messages "
                "WHERE id = ? AND session_id = ?",
                (message_id, source_session_id),
            )
            target = await cursor.fetchone()
            if not target:
                raise LookupError("Message not found")

            created_at = target["created_at"] or ""
            cursor = await db.execute(
                "SELECT role, content, tool_calls, token_usage, created_at "
                "FROM messages WHERE session_id = ? AND created_at <= ? "
                "ORDER BY created_at",
                (source_session_id, created_at),
            )
            rows = await cursor.fetchall()

            new_session_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            base_title = (source["title"] or "").strip() or "未命名"
            suffix = " (分支)"
            max_base = 50 - len(suffix)
            title = (base_title[:max_base] + suffix) if len(base_title) > max_base else (base_title + suffix)

            await db.execute(
                "INSERT INTO sessions "
                "(id, agent_id, title, status, current_task_id, "
                " input_tokens, output_tokens, cost_usd, "
                " cache_read_tokens, cache_creation_tokens, "
                " context_mode, collaboration_mode, created_at) "
                "VALUES (?, ?, ?, 'active', NULL, 0, 0, 0, 0, 0, ?, ?, ?)",
                (
                    new_session_id,
                    source["agent_id"],
                    title,
                    source["context_mode"] or "chat",
                    source["collaboration_mode"] or "agent",
                    now,
                ),
            )

            for r in rows:
                await db.execute(
                    "INSERT INTO messages "
                    "(id, session_id, role, content, tool_calls, token_usage, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(uuid.uuid4()),
                        new_session_id,
                        r["role"],
                        r["content"],
                        r["tool_calls"],
                        r["token_usage"],
                        r["created_at"],
                    ),
                )
            await db.commit()

        return new_session_id

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
