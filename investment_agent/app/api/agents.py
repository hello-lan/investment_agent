"""Agent 配置 API 路由 — 薄层，委托 AgentService 处理业务逻辑。"""

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ..services.agent_service import AgentService

router = APIRouter(prefix="/api/agents", tags=["agents"])


class AgentEntry(BaseModel):
    """自定义 Agent 配置模型"""
    name: str
    description: str = ""
    system_prompt: str = ""
    model_id: str = ""
    temperature: float = 0.7
    max_single_turn_output_tokens: int = 4096  # 单轮 LLM 回复的最大输出 token
    skills: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    subagents: list[str] = Field(default_factory=list)
    compress_config: dict | None = None
    engine_config: dict | None = None
    avatar: str = ""
    show_in_composer: bool = False
    composer_sort: int = 0


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
        max_single_turn_output_tokens=body.max_single_turn_output_tokens,
        skills=body.skills,
        tools=body.tools,
        subagents=body.subagents,
        compress_config=body.compress_config,
        engine_config=body.engine_config,
        avatar=body.avatar,
        show_in_composer=body.show_in_composer,
        composer_sort=body.composer_sort,
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
        max_single_turn_output_tokens=body.max_single_turn_output_tokens,
        skills=body.skills,
        tools=body.tools,
        subagents=body.subagents,
        compress_config=body.compress_config,
        engine_config=body.engine_config,
        avatar=body.avatar,
        show_in_composer=body.show_in_composer,
        composer_sort=body.composer_sort,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"success": True}


@router.post("/{agent_id}/avatar")
async def upload_avatar(agent_id: str, file: UploadFile = File(...)):
    content = await file.read()
    try:
        rel = await AgentService.save_avatar(agent_id, file.filename or "", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if rel is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"avatar": rel}


@router.delete("/{agent_id}")
async def delete_agent(agent_id: str):
    await AgentService.delete_agent(agent_id)
    return {"success": True}
