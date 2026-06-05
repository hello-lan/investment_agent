"""Agent 配置 API 路由 — 薄层，委托 AgentService 处理业务逻辑。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.agent_service import AgentService

router = APIRouter(prefix="/api/agents", tags=["agents"])


class AgentEntry(BaseModel):
    """自定义 Agent 配置模型"""
    name: str
    description: str = ""
    system_prompt: str = ""
    model_id: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    skills: list[str] = []
    tools: list[str] = []
    compress_config: dict | None = None
    engine_config: dict | None = None


@router.get("")
async def list_agents():
    return await AgentService.list_agents()


@router.post("")
async def create_agent(body: AgentEntry):
    agent_id = await AgentService.create_agent(
        name=body.name,
        description=body.description,
        system_prompt=body.system_prompt,
        model_id=body.model_id,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        skills=body.skills,
        tools=body.tools,
        compress_config=body.compress_config,
        engine_config=body.engine_config,
    )
    return {"id": agent_id}


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    agent = await AgentService.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.put("/{agent_id}")
async def update_agent(agent_id: str, body: AgentEntry):
    ok = await AgentService.update_agent(
        agent_id=agent_id,
        name=body.name,
        description=body.description,
        system_prompt=body.system_prompt,
        model_id=body.model_id,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        skills=body.skills,
        tools=body.tools,
        compress_config=body.compress_config,
        engine_config=body.engine_config,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"success": True}


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str):
    await AgentService.delete_agent(agent_id)
    return {"success": True}
