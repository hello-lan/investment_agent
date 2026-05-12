import uuid
from datetime import datetime
from fastapi import APIRouter
from pydantic import BaseModel
from ...config import get_settings, save_settings
from ...agent.skills.loader import reload_skills
from ..db import get_db

router = APIRouter(prefix="/api/settings", tags=["settings"])


# ── 模型管理（CRUD + 默认值 + 连接测试）────────────────────────────────────

class ModelEntry(BaseModel):
    id: str = ""       # 为空则自动生成
    name: str
    type: str          # "anthropic" | "openai_compat"
    api_key: str = ""  # 更新时传 "***" 保留原值
    model: str
    base_url: str = ""


@router.get("/models")
async def list_models():
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, name, type, model, base_url, is_default FROM models ORDER BY created_at"
        )
        rows = await cursor.fetchall()
    return {
        "default": next((r["id"] for r in rows if r["is_default"]), None),
        "list": [dict(r) for r in rows],
    }


@router.post("/models")
async def add_model(body: ModelEntry):
    """添加模型：第一个模型自动设为默认"""
    mid = body.id.strip() or str(uuid.uuid4())[:8]
    now = datetime.utcnow().isoformat()
    async with get_db() as db:
        row = await db.execute("SELECT id FROM models WHERE id = ?", (mid,))
        if await row.fetchone():
            return {"error": f"Model id '{mid}' already exists."}
        # 首个模型自动成为默认
        count = await db.execute("SELECT COUNT(*) FROM models")
        is_first = (await count.fetchone())[0] == 0
        await db.execute(
            "INSERT INTO models (id, name, type, api_key, model, base_url, is_default, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (mid, body.name, body.type, body.api_key, body.model, body.base_url, 1 if is_first else 0, now),
        )
        await db.commit()
    return {"id": mid}


@router.put("/models/default")
async def set_default_model(body: dict):
    """设置默认模型：先将所有模型置为 0，再设置目标模型为 1"""
    model_id = body.get("model_id", "")
    async with get_db() as db:
        await db.execute("UPDATE models SET is_default = 0")
        await db.execute("UPDATE models SET is_default = 1 WHERE id = ?", (model_id,))
        await db.commit()
    return {"success": True}


@router.put("/models/{model_id}")
async def update_model(model_id: str, body: ModelEntry):
    """更新模型：API Key 传 "***" 时保留原值（前端脱敏回传）"""
    async with get_db() as db:
        row = await db.execute("SELECT api_key FROM models WHERE id = ?", (model_id,))
        existing = await row.fetchone()
        if not existing:
            return {"error": "Model not found"}
        # 前端传来脱敏值 *** 表示不修改 Key
        api_key = existing["api_key"] if body.api_key == "***" else body.api_key
        await db.execute(
            "UPDATE models SET name=?, type=?, api_key=?, model=?, base_url=? WHERE id=?",
            (body.name, body.type, api_key, body.model, body.base_url, model_id),
        )
        await db.commit()
    return {"success": True}


@router.delete("/models/{model_id}")
async def delete_model(model_id: str):
    """删除模型：如果删除的是默认模型，自动将第一个剩余模型设为默认"""
    async with get_db() as db:
        row = await db.execute("SELECT is_default FROM models WHERE id = ?", (model_id,))
        m = await row.fetchone()
        await db.execute("DELETE FROM models WHERE id = ?", (model_id,))
        # 删除默认模型时，将第一个剩余模型提升为默认
        if m and m["is_default"]:
            await db.execute(
                "UPDATE models SET is_default = 1 WHERE id = (SELECT id FROM models LIMIT 1)"
            )
        await db.commit()
    return {"success": True}


class TestModelRequest(BaseModel):
    model_id: str


@router.post("/models/test")
async def test_model(body: TestModelRequest):
    """测试模型连接：发送一个简单请求验证 API Key 和 endpoint 是否可用"""
    try:
        from ...agent.core.models import get_provider
        provider = await get_provider(body.model_id)
        resp = await provider.chat(
            messages=[{"role": "user", "content": "reply with the single word: ok"}],
            max_tokens=10,
        )
        return {"ok": True, "response": resp.content}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ── Engine & Tools ────────────────────────────────────────────────────────────

@router.get("")
async def read_settings():
    s = get_settings()
    return {k: v for k, v in s.items() if k != "models"}


class EngineSettings(BaseModel):
    max_steps: int
    slow_think_interval: int
    token_budget: int
    loop_detection_threshold: int


@router.put("/engine")
async def update_engine(body: EngineSettings):
    s = get_settings()
    s["engine"] = body.model_dump()
    save_settings(s)
    return {"success": True}


class ToolsSettings(BaseModel):
    tushare_token: str = ""


class CompressSettings(BaseModel):
    enabled: bool = True
    recent_keep: int = 6
    max_chars_per_msg: int = 2000
    total_budget_chars: int = 20000


@router.put("/compress")
async def update_compress(body: CompressSettings):
    s = get_settings()
    s["compress"] = {
        "enabled": bool(body.enabled),
        "recent_keep": max(0, body.recent_keep),
        "max_chars_per_msg": max(200, body.max_chars_per_msg),
        "total_budget_chars": max(2000, body.total_budget_chars),
    }
    save_settings(s)
    return {"success": True}


class SkillsSettings(BaseModel):
    directory: str = "skills"


@router.put("/skills")
async def update_skills(body: SkillsSettings):
    s = get_settings()
    s["skills"] = {
        "directory": (body.directory or "skills").strip() or "skills",
    }
    save_settings(s)
    reload_skills()
    return {"success": True}


@router.put("/tools")
async def update_tools(body: ToolsSettings):
    s = get_settings()
    existing = s.get("tools", {})
    token = existing.get("tushare_token", "") if body.tushare_token == "***" else body.tushare_token
    s["tools"] = {"tushare_token": token}
    save_settings(s)
    return {"success": True}
