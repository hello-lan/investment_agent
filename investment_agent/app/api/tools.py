"""工具目录与检索实例配置。"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import httpx

from ...agent.registry_container import AgentRegistry
from ...agent.tools.rag_retrieve import default_template, describe_instance
from ..services.tool_instances import (
    delete_tool_instance,
    get_tool_instance_by_id,
    list_tool_instances,
    save_tool_instance,
)

router = APIRouter(prefix="/api/tools", tags=["tools"])


class InstanceBody(BaseModel):
    display_name: str
    tool_name: str
    description: str = ""
    base_url: str
    path: str = "/retrieve"
    timeout_seconds: int = 90
    params: list[dict] = Field(default_factory=list)


class TestBody(BaseModel):
    base_url: str


def _builtin_infos() -> list[dict]:
    registry = AgentRegistry()
    registry.bootstrap_default_tools()
    infos = registry.get_all_tool_infos()
    for item in infos:
        item["kind"] = "builtin"
    return infos


def _instance_summary(instance: dict) -> dict:
    return {
        "name": instance["tool_name"],
        "label": instance["display_name"],
        "description": describe_instance(instance),
        "auto_bound": False,
        "kind": "instance",
        "template": instance["template"],
    }


@router.get("")
async def list_tools():
    """内置工具加上已保存的检索实例。Agent 页用 label 显示实例名。"""
    instances = await list_tool_instances()
    return _builtin_infos() + [_instance_summary(item) for item in instances]


@router.get("/templates")
async def list_templates():
    return {"templates": [default_template()]}


@router.get("/instances")
async def list_instances():
    return await list_tool_instances()


@router.post("/instances")
async def create_instance(body: InstanceBody):
    saved, error = await save_tool_instance(body.model_dump())
    if error:
        raise HTTPException(status_code=400, detail=error)
    return saved


@router.put("/instances/{instance_id}")
async def update_instance(instance_id: str, body: InstanceBody):
    current = await get_tool_instance_by_id(instance_id)
    if current is None:
        raise HTTPException(status_code=404, detail="工具配置不存在。")
    saved, error = await save_tool_instance(body.model_dump(), instance_id)
    if error:
        raise HTTPException(status_code=400, detail=error)
    return saved


@router.delete("/instances/{instance_id}")
async def remove_instance(instance_id: str):
    deleted = await delete_tool_instance(instance_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="工具配置不存在。")
    return {"ok": True}


@router.post("/test")
async def test_connection(body: TestBody):
    """请求 {base_url}/health。连不上时只返回说明，不阻止随后保存。"""
    base = (body.base_url or "").strip().rstrip("/")
    if not base.startswith("http://") and not base.startswith("https://"):
        return {"ok": False, "error": "服务地址需要是 http 或 https URL。"}
    url = base + "/health"
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            response = await client.get(url)
    except httpx.TimeoutException:
        return {"ok": False, "error": "连接超时。"}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"无法连接：{exc}"}
    text = response.text[:500]
    return {
        "ok": response.status_code < 400,
        "status_code": response.status_code,
        "body": text,
    }
