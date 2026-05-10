import json
import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from ..db import get_db

router = APIRouter(prefix="/api/agents", tags=["agents"])


class AgentEntry(BaseModel):
    name: str
    description: str = ""
    system_prompt: str = ""
    model_id: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    skills: list[str] = []


@router.get("")
async def list_agents():
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, name, description, system_prompt, model_id, temperature, max_tokens, skills, created_at, updated_at FROM agents ORDER BY created_at"
        )
        rows = await cursor.fetchall()
    return [dict(r) for r in rows]


@router.post("")
async def create_agent(body: AgentEntry):
    agent_id = str(uuid.uuid4())[:8]
    now = datetime.utcnow().isoformat()
    async with get_db() as db:
        await db.execute(
            "INSERT INTO agents (id, name, description, system_prompt, model_id, temperature, max_tokens, skills, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (agent_id, body.name, body.description, body.system_prompt, body.model_id,
             body.temperature, body.max_tokens, json.dumps(body.skills), now, now),
        )
        await db.commit()
    return {"id": agent_id}


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    async with get_db() as db:
        row = await db.execute("SELECT * FROM agents WHERE id = ?", (agent_id,))
        agent = await row.fetchone()
    if not agent:
        return {"error": "Agent not found"}
    return dict(agent)


@router.put("/{agent_id}")
async def update_agent(agent_id: str, body: AgentEntry):
    now = datetime.utcnow().isoformat()
    async with get_db() as db:
        row = await db.execute("SELECT id FROM agents WHERE id = ?", (agent_id,))
        if not await row.fetchone():
            return {"error": "Agent not found"}
        await db.execute(
            "UPDATE agents SET name=?, description=?, system_prompt=?, model_id=?, temperature=?, max_tokens=?, skills=?, updated_at=? WHERE id=?",
            (body.name, body.description, body.system_prompt, body.model_id,
             body.temperature, body.max_tokens, json.dumps(body.skills), now, agent_id),
        )
        await db.commit()
    return {"success": True}


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str):
    async with get_db() as db:
        await db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        await db.commit()
    return {"success": True}
