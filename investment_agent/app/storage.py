"""SqliteStorage — 实现 agent.protocols.Storage 协议。

封装 agent 所需的所有 DB 操作，agent 包不直接依赖 app.db。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from .db import get_db

logger = logging.getLogger(__name__)


class SqliteStorage:
    """SQLite 持久化实现，满足 agent.protocols.Storage 协议。"""

    async def create_or_get_session(
        self, session_id: str, agent_id: str | None, title: str,
    ) -> str:
        """创建或复用会话，返回 session_id。"""
        async with get_db() as db:
            row = await db.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
            exists = await row.fetchone()
            if not exists:
                now = datetime.utcnow().isoformat()
                await db.execute(
                    "INSERT INTO sessions (id, agent_id, title, status, created_at) "
                    "VALUES (?, ?, ?, 'active', ?)",
                    (session_id, agent_id, title[:50], now),
                )
                await db.commit()
        return session_id

    async def save_user_message(self, session_id: str, content: str) -> str:
        """保存用户消息，返回 message_id。"""
        msg_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        async with get_db() as db:
            await db.execute(
                "INSERT INTO messages (id, session_id, role, content, created_at) "
                "VALUES (?, ?, 'user', ?, ?)",
                (msg_id, session_id, content, now),
            )
            await db.commit()
        return msg_id

    async def save_assistant_message(self, session_id: str, content: str) -> str:
        """保存 assistant 回复，返回 message_id。"""
        if not content:
            return ""
        msg_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        async with get_db() as db:
            await db.execute(
                "INSERT INTO messages (id, session_id, role, content, created_at) "
                "VALUES (?, ?, 'assistant', ?, ?)",
                (msg_id, session_id, content, now),
            )
            await db.commit()
        return msg_id

    async def load_messages(self, session_id: str) -> list[dict]:
        """加载会话的所有历史消息，合并连续同角色消息避免重试累积。"""
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY created_at",
                (session_id,),
            )
            rows = await cursor.fetchall()
        messages: list[dict] = []
        for r in rows:
            if r["role"] in ("user", "assistant"):
                messages.append({"role": r["role"], "content": r["content"] or ""})
        return self._dedupe_consecutive(messages)

    @staticmethod
    def _dedupe_consecutive(messages: list[dict]) -> list[dict]:
        """当连续出现同角色消息（前次运行未完成就重试所致），仅保留最后一条。"""
        if len(messages) <= 1:
            return messages

        result = []
        i = len(messages) - 1
        while i >= 0:
            current = messages[i]
            role = current.get("role", "")
            # 跳过前面与当前同角色的连续消息
            j = i - 1
            while j >= 0 and messages[j].get("role") == role:
                j -= 1
            result.append(current)
            i = j

        result.reverse()
        return result

    async def load_summary(self, session_id: str) -> str | None:
        """从 DB 加载已有摘要。"""
        try:
            async with get_db() as db:
                row = await db.execute(
                    "SELECT summary_content FROM session_summaries WHERE session_id = ?",
                    (session_id,),
                )
                record = await row.fetchone()
                if record and record["summary_content"]:
                    return record["summary_content"]
        except Exception:
            logger.debug("Failed to load summary for session %s", session_id, exc_info=True)
        return None

    async def save_summary(
        self, session_id: str, summary: str,
        through_message_id: str, token_count: int,
    ) -> None:
        """保存/更新摘要到 DB。"""
        try:
            now = datetime.now(timezone.utc).isoformat()
            async with get_db() as db:
                await db.execute(
                    """INSERT INTO session_summaries
                       (id, session_id, summary_content, summarized_through_id,
                        summary_token_count, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(session_id) DO UPDATE SET
                        summary_content = excluded.summary_content,
                        summarized_through_id = excluded.summarized_through_id,
                        summary_token_count = excluded.summary_token_count,
                        updated_at = excluded.updated_at""",
                    (str(uuid.uuid4()), session_id, summary, through_message_id,
                     token_count, now, now),
                )
                await db.commit()
        except Exception:
            logger.exception("Failed to save summary for session %s", session_id)

    async def get_agent_config(self, agent_id: str) -> dict | None:
        """查询 agent 配置。"""
        async with get_db() as db:
            row = await db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
            result = await row.fetchone()
            return dict(result) if result else None

    async def get_model_config(self, model_id: str | None = None) -> dict | None:
        """查询模型配置。默认模型时 model_id 为 None。"""
        async with get_db() as db:
            if model_id:
                row = await db.execute("SELECT * FROM models WHERE id = ?", (model_id,))
            else:
                row = await db.execute("SELECT * FROM models WHERE is_default = 1 LIMIT 1")
            cfg = await row.fetchone()
            if not cfg:
                row = await db.execute("SELECT * FROM models LIMIT 1")
                cfg = await row.fetchone()
        return dict(cfg) if cfg else None

    async def get_session_agent_id(self, session_id: str) -> str | None:
        """查询会话绑定的 agent_id。"""
        async with get_db() as db:
            row = await db.execute("SELECT agent_id FROM sessions WHERE id = ?", (session_id,))
            session = await row.fetchone()
            if session:
                return session["agent_id"]
        return None

    async def update_session_task(
        self, session_id: str, *, status: str, task_id: str | None = None,
    ) -> None:
        """更新会话的运行状态和当前 task_id。"""
        async with get_db() as db:
            await db.execute(
                "UPDATE sessions SET status = ?, current_task_id = ? WHERE id = ?",
                (status, task_id, session_id),
            )
            await db.commit()

    async def update_session_usage(
        self, session_id: str, *, input_tokens: int, output_tokens: int, cost_usd: float,
    ) -> None:
        """累加会话的 token 用量和费用。"""
        async with get_db() as db:
            await db.execute(
                "UPDATE sessions SET "
                "input_tokens = COALESCE(input_tokens, 0) + ?, "
                "output_tokens = COALESCE(output_tokens, 0) + ?, "
                "cost_usd = COALESCE(cost_usd, 0) + ? "
                "WHERE id = ?",
                (input_tokens, output_tokens, cost_usd, session_id),
            )
            await db.commit()

    async def get_session_running_task(self, session_id: str) -> str | None:
        """查询会话当前运行中的 task_id（仅 status='running' 时返回）。"""
        async with get_db() as db:
            row = await db.execute(
                "SELECT current_task_id FROM sessions WHERE id = ? AND status = 'running'",
                (session_id,),
            )
            session = await row.fetchone()
            if session:
                return session["current_task_id"]
        return None
