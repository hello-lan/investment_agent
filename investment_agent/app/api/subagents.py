"""Subagent 定义 API 路由。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services.subagent_service import SubagentService

router = APIRouter(prefix="/api/subagents", tags=["subagents"])


class SubagentEntry(BaseModel):
    name: str
    description: str = ""
    system_prompt: str = ""
    model_id: str = ""
    tools: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    runtime_config: dict | None = None


@router.get("")
async def list_subagents():
    return await SubagentService.list_subagents()


@router.post("")
async def create_subagent(body: SubagentEntry):
    try:
        subagent_id = await SubagentService.create_subagent(
            name=body.name,
            description=body.description,
            system_prompt=body.system_prompt,
            model_id=body.model_id,
            tools=body.tools,
            skills=body.skills,
            runtime_config=body.runtime_config,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"id": subagent_id}


@router.get("/{subagent_id}")
async def get_subagent(subagent_id: str):
    item = await SubagentService.get_subagent(subagent_id)
    if not item:
        raise HTTPException(status_code=404, detail="Subagent not found")
    return item


@router.put("/{subagent_id}")
async def update_subagent(subagent_id: str, body: SubagentEntry):
    try:
        ok = await SubagentService.update_subagent(
            subagent_id=subagent_id,
            name=body.name,
            description=body.description,
            system_prompt=body.system_prompt,
            model_id=body.model_id,
            tools=body.tools,
            skills=body.skills,
            runtime_config=body.runtime_config,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not ok:
        raise HTTPException(status_code=404, detail="Subagent not found")
    return {"success": True}


@router.delete("/{subagent_id}")
async def delete_subagent(subagent_id: str):
    try:
        await SubagentService.delete_subagent(subagent_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return {"success": True}
