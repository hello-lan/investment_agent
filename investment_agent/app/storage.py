"""SqliteStorage — 实现 agent.protocols.Storage 协议。

封装 agent 所需的所有 DB 操作，agent 包不直接依赖 app.db。
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from .db import get_db

logger = logging.getLogger(__name__)


class SqliteStorage:
    """SQLite 持久化实现，满足 agent.protocols.Storage 协议。"""

    async def create_or_get_session(
        self, session_id: str, agent_id: str | None, title: str,
        context_mode: str | None = None,
        collaboration_mode: str | None = None,
    ) -> str:
        """创建或复用会话，返回 session_id。"""
        mode = context_mode if context_mode in ("chat", "full") else None
        collab = collaboration_mode if collaboration_mode in ("agent", "plan") else None
        async with get_db() as db:
            row = await db.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
            exists = await row.fetchone()
            if not exists:
                now = datetime.now(timezone.utc).isoformat()
                await db.execute(
                    "INSERT INTO sessions "
                    "(id, agent_id, title, status, context_mode, collaboration_mode, created_at) "
                    "VALUES (?, ?, ?, 'active', ?, ?, ?)",
                    (session_id, agent_id, title[:50], mode or "chat", collab or "agent", now),
                )
                await db.commit()
            else:
                updates = []
                params: list = []
                if mode:
                    updates.append("context_mode = ?")
                    params.append(mode)
                if collab:
                    updates.append("collaboration_mode = ?")
                    params.append(collab)
                if updates:
                    params.append(session_id)
                    await db.execute(
                        f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?",
                        params,
                    )
                    await db.commit()
        return session_id

    async def save_user_message(self, session_id: str, content: str) -> str:
        """保存用户消息，返回 message_id。"""
        msg_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
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

    async def get_context_mode(self, session_id: str) -> str:
        """查询会话的上下文回放方式。缺省为 chat。"""
        async with get_db() as db:
            row = await db.execute(
                "SELECT context_mode FROM sessions WHERE id = ?", (session_id,),
            )
            result = await row.fetchone()
        if not result:
            return "chat"
        mode = result["context_mode"] or "chat"
        return mode if mode in ("chat", "full") else "chat"

    async def set_context_mode(self, session_id: str, mode: str) -> None:
        """设置会话的上下文回放方式。"""
        if mode not in ("chat", "full"):
            raise ValueError(f"invalid context mode: {mode}")
        async with get_db() as db:
            await db.execute(
                "UPDATE sessions SET context_mode = ? WHERE id = ?",
                (mode, session_id),
            )
            await db.commit()

    async def get_collaboration_mode(self, session_id: str) -> str:
        """查询会话协作模式。缺省为 agent。"""
        async with get_db() as db:
            row = await db.execute(
                "SELECT collaboration_mode FROM sessions WHERE id = ?", (session_id,),
            )
            result = await row.fetchone()
        if not result:
            return "agent"
        mode = result["collaboration_mode"] or "agent"
        return mode if mode in ("agent", "plan") else "agent"

    async def set_collaboration_mode(self, session_id: str, mode: str) -> None:
        """设置会话协作模式。"""
        if mode not in ("agent", "plan"):
            raise ValueError(f"invalid collaboration mode: {mode}")
        async with get_db() as db:
            await db.execute(
                "UPDATE sessions SET collaboration_mode = ? WHERE id = ?",
                (mode, session_id),
            )
            await db.commit()

    async def latest_user_message_id(self, session_id: str) -> str | None:
        """最近一条用户消息的 id。"""
        async with get_db() as db:
            row = await db.execute(
                "SELECT id FROM messages WHERE session_id = ? AND role = 'user' "
                "ORDER BY created_at DESC LIMIT 1",
                (session_id,),
            )
            result = await row.fetchone()
        return result["id"] if result else None

    async def save_context_snapshot(
        self, session_id: str, user_message_id: str | None, messages: list,
    ) -> None:
        """保存一轮结束时模型实际看到的完整消息。"""
        if not messages:
            return
        snap_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        payload = json.dumps(messages, ensure_ascii=False)
        async with get_db() as db:
            await db.execute(
                "INSERT INTO context_snapshots "
                "(id, session_id, user_message_id, messages, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (snap_id, session_id, user_message_id, payload, now),
            )
            await db.commit()

    async def load_messages(self, session_id: str, mode: str | None = None) -> list[dict]:
        """加载历史。chat 只含可见对话；full 用最新快照，并接上快照之后的新消息。"""
        if mode is None:
            mode = await self.get_context_mode(session_id)
        visible = await self._load_visible_rows(session_id)
        if mode != "full":
            return self._dedupe_consecutive(visible)

        snapshot = await self._latest_snapshot(session_id)
        if not snapshot:
            return self._dedupe_consecutive(visible)

        try:
            messages = json.loads(snapshot["messages"] or "[]")
        except json.JSONDecodeError:
            logger.warning("context snapshot JSON invalid for session %s", session_id)
            return self._dedupe_consecutive(visible)
        if not isinstance(messages, list):
            return self._dedupe_consecutive(visible)

        snap_at = snapshot["created_at"] or ""
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT role, content FROM messages "
                "WHERE session_id = ? AND created_at > ? ORDER BY created_at",
                (session_id, snap_at),
            )
            tail = await cursor.fetchall()
        for r in tail:
            if r["role"] in ("user", "assistant"):
                messages.append({"role": r["role"], "content": r["content"] or ""})
        return messages

    async def _load_visible_rows(self, session_id: str) -> list[dict]:
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
        return messages

    async def _latest_snapshot(self, session_id: str):
        async with get_db() as db:
            row = await db.execute(
                "SELECT messages, created_at FROM context_snapshots "
                "WHERE session_id = ? ORDER BY created_at DESC LIMIT 1",
                (session_id,),
            )
            return await row.fetchone()

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

    async def get_utility_model_config(self) -> dict | None:
        """查询辅助模型配置（is_utility=1）。未设置则返回 None。"""
        async with get_db() as db:
            row = await db.execute(
                "SELECT * FROM models WHERE is_utility = 1 LIMIT 1"
            )
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
        cache_read_tokens: int = 0, cache_creation_tokens: int = 0, currency: str = "USD",
    ) -> None:
        """累加会话的 token 用量和费用。"""
        async with get_db() as db:
            await db.execute(
                "UPDATE sessions SET "
                "input_tokens = COALESCE(input_tokens, 0) + ?, "
                "output_tokens = COALESCE(output_tokens, 0) + ?, "
                "cost_usd = COALESCE(cost_usd, 0) + ?, "
                "cache_read_tokens = COALESCE(cache_read_tokens, 0) + ?, "
                "cache_creation_tokens = COALESCE(cache_creation_tokens, 0) + ?, "
                "currency = CASE WHEN currency IS NULL THEN ? ELSE currency END "
                "WHERE id = ?",
                (input_tokens, output_tokens, cost_usd,
                 cache_read_tokens, cache_creation_tokens, currency,
                 session_id),
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
