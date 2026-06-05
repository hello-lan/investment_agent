"""Agent 配置服务层 — 封装 agents 相关的所有 DB 操作。

从 app/api/agents.py 提取，分离 HTTP 路由与数据访问逻辑。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from ..db import get_db


class AgentService:
    """Agent 配置 CRUD。"""

    @staticmethod
    async def list_agents() -> list[dict]:
        """获取所有 Agent 配置列表。"""
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT id, name, description, system_prompt, model_id, "
                "temperature, max_tokens, skills, tools, "
                "compress_config, engine_config, created_at, updated_at "
                "FROM agents ORDER BY created_at"
            )
            rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    async def create_agent(
        name: str,
        description: str = "",
        system_prompt: str = "",
        model_id: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        skills: list[str] | None = None,
        tools: list[str] | None = None,
        compress_config: dict | None = None,
        engine_config: dict | None = None,
    ) -> str:
        """创建新 Agent，返回 agent_id。"""
        agent_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()
        async with get_db() as db:
            await db.execute(
                "INSERT INTO agents (id, name, description, system_prompt, "
                "model_id, temperature, max_tokens, skills, tools, "
                "compress_config, engine_config, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    agent_id, name, description, system_prompt,
                    model_id, temperature, max_tokens,
                    json.dumps(skills or []),
                    json.dumps(tools or []),
                    json.dumps(compress_config) if compress_config is not None else None,
                    json.dumps(engine_config) if engine_config is not None else None,
                    now, now,
                ),
            )
            await db.commit()
        return agent_id

    @staticmethod
    async def get_agent(agent_id: str) -> dict | None:
        """获取单个 Agent 配置。"""
        async with get_db() as db:
            row = await db.execute(
                "SELECT * FROM agents WHERE id = ?", (agent_id,)
            )
            agent = await row.fetchone()
            return dict(agent) if agent else None

    @staticmethod
    async def update_agent(
        agent_id: str,
        name: str,
        description: str = "",
        system_prompt: str = "",
        model_id: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        skills: list[str] | None = None,
        tools: list[str] | None = None,
        compress_config: dict | None = None,
        engine_config: dict | None = None,
    ) -> bool:
        """更新 Agent 配置，返回是否成功（False = 不存在）。"""
        now = datetime.now(timezone.utc).isoformat()
        async with get_db() as db:
            row = await db.execute(
                "SELECT id FROM agents WHERE id = ?", (agent_id,)
            )
            if not await row.fetchone():
                return False

            await db.execute(
                "UPDATE agents SET name=?, description=?, system_prompt=?, "
                "model_id=?, temperature=?, max_tokens=?, skills=?, tools=?, "
                "compress_config=?, engine_config=?, updated_at=? WHERE id=?",
                (
                    name, description, system_prompt,
                    model_id, temperature, max_tokens,
                    json.dumps(skills or []),
                    json.dumps(tools or []),
                    json.dumps(compress_config) if compress_config is not None else None,
                    json.dumps(engine_config) if engine_config is not None else None,
                    now, agent_id,
                ),
            )
            await db.commit()
        return True

    @staticmethod
    async def delete_agent(agent_id: str) -> None:
        """删除 Agent 配置。"""
        async with get_db() as db:
            await db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
            await db.commit()
