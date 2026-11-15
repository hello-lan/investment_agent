"""Workflow 配置 API 路由。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services.workflow_service import WorkflowService

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


class WorkflowEntry(BaseModel):
    name: str
    description: str = ""
    definition: dict


class WorkflowValidateRequest(BaseModel):
    definition: dict


@router.get("")
async def list_workflows():
    return await WorkflowService.list_workflows()


@router.post("/validate")
async def validate_workflow(body: WorkflowValidateRequest):
    try:
        return await WorkflowService.validate_definition(body.definition)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("")
async def create_workflow(body: WorkflowEntry):
    try:
        workflow_id = await WorkflowService.create_workflow(
            name=body.name,
            description=body.description,
            definition=body.definition,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": workflow_id}


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: str):
    workflow = await WorkflowService.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow


@router.put("/{workflow_id}")
async def update_workflow(workflow_id: str, body: WorkflowEntry):
    try:
        ok = await WorkflowService.update_workflow(
            workflow_id=workflow_id,
            name=body.name,
            description=body.description,
            definition=body.definition,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not ok:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"success": True}


@router.delete("/{workflow_id}")
async def delete_workflow(workflow_id: str):
    await WorkflowService.delete_workflow(workflow_id)
    return {"success": True}
