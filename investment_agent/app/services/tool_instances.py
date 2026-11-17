"""检索工具实例的校验和持久化。"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from ...agent.registry_container import AgentRegistry
from ...agent.tools.rag_retrieve import (
    DEFAULT_PATH,
    DEFAULT_TIMEOUT,
    PARAM_TYPES,
    TEMPLATE_ID,
)
from ..db import get_db

_TOOL_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_PARAM_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def builtin_tool_names() -> set[str]:
    registry = AgentRegistry()
    registry.bootstrap_default_tools()
    return set(registry.tools)


def _clean_param(raw: dict) -> dict:
    source = raw.get("source")
    if source not in ("llm", "fixed"):
        source = "llm"
    typ = raw.get("type") or "string"
    if typ not in PARAM_TYPES:
        typ = "string"
    return {
        "key": str(raw.get("key") or "").strip(),
        "source": source,
        "type": typ,
        "required": bool(raw.get("required")) if source == "llm" else False,
        "description": str(raw.get("description") or "").strip(),
        "value": "" if raw.get("value") is None else str(raw.get("value")),
    }


def validate_instance(data: dict, *, builtin_names: set[str] | None = None) -> str | None:
    """返回错误说明；通过时返回 None。"""
    display_name = str(data.get("display_name") or "").strip()
    tool_name = str(data.get("tool_name") or "").strip()
    base_url = str(data.get("base_url") or "").strip()
    if not display_name:
        return "请填写显示名。"
    if not _TOOL_NAME.match(tool_name):
        return "调用名需以英文字母开头，只能包含字母、数字和下划线。"
    if builtin_names and tool_name in builtin_names:
        return f"调用名 {tool_name} 与内置工具重名。"
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "服务地址需要是 http 或 https URL。"
    path = str(data.get("path") or DEFAULT_PATH).strip() or DEFAULT_PATH
    if not path.startswith("/"):
        return "路径需要以 / 开头。"
    try:
        timeout = int(data.get("timeout_seconds") if data.get("timeout_seconds") is not None else DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        return "超时需要是整数秒。"
    if timeout < 1 or timeout > 600:
        return "超时需要在 1 到 600 秒之间。"
    params = data.get("params") or []
    if not isinstance(params, list) or not params:
        return "至少添加一个请求参数。"
    seen: set[str] = set()
    llm_count = 0
    for raw in params:
        if not isinstance(raw, dict):
            return "请求参数格式不正确。"
        param = _clean_param(raw)
        if not _PARAM_KEY.match(param["key"]):
            return "参数名需以字母或下划线开头，只能包含字母、数字和下划线。"
        if param["key"] in seen:
            return f"参数名 {param['key']} 重复。"
        seen.add(param["key"])
        if param["source"] == "llm":
            llm_count += 1
        elif not str(param["value"]).strip():
            return f"固定参数 {param['key']} 需要填写值。"
    if llm_count < 1:
        return "至少保留一个由模型填写的参数。"
    return None


def normalize_payload(data: dict) -> dict:
    path = str(data.get("path") or DEFAULT_PATH).strip() or DEFAULT_PATH
    timeout = int(data.get("timeout_seconds") if data.get("timeout_seconds") is not None else DEFAULT_TIMEOUT)
    params = [_clean_param(item) for item in data.get("params") or [] if isinstance(item, dict)]
    return {
        "display_name": str(data.get("display_name") or "").strip(),
        "tool_name": str(data.get("tool_name") or "").strip(),
        "description": str(data.get("description") or "").strip(),
        "base_url": str(data.get("base_url") or "").strip().rstrip("/"),
        "path": path,
        "timeout_seconds": timeout,
        "params": params,
    }


def _row_to_instance(row) -> dict:
    cfg = json.loads(row["config_json"] or "{}")
    return {
        "id": row["id"],
        "template": row["template"],
        "display_name": row["display_name"],
        "tool_name": row["tool_name"],
        "description": cfg.get("description") or "",
        "base_url": cfg.get("base_url") or "",
        "path": cfg.get("path") or DEFAULT_PATH,
        "timeout_seconds": cfg.get("timeout_seconds") or DEFAULT_TIMEOUT,
        "params": cfg.get("params") or [],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _config_json(payload: dict) -> str:
    return json.dumps(
        {
            "description": payload["description"],
            "base_url": payload["base_url"],
            "path": payload["path"],
            "timeout_seconds": payload["timeout_seconds"],
            "params": payload["params"],
        },
        ensure_ascii=False,
    )


async def list_tool_instances() -> list[dict]:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, template, display_name, tool_name, config_json, created_at, updated_at "
            "FROM tool_instances ORDER BY created_at"
        )
        rows = await cursor.fetchall()
    return [_row_to_instance(row) for row in rows]


async def get_tool_instance(tool_name: str) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, template, display_name, tool_name, config_json, created_at, updated_at "
            "FROM tool_instances WHERE tool_name = ?",
            (tool_name,),
        )
        row = await cursor.fetchone()
    if row is None:
        return None
    return _row_to_instance(row)


async def get_tool_instance_by_id(instance_id: str) -> dict | None:
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id, template, display_name, tool_name, config_json, created_at, updated_at "
            "FROM tool_instances WHERE id = ?",
            (instance_id,),
        )
        row = await cursor.fetchone()
    if row is None:
        return None
    return _row_to_instance(row)


async def save_tool_instance(data: dict, instance_id: str | None = None) -> tuple[dict | None, str | None]:
    """校验并保存。成功返回 (实例, None)，失败返回 (None, 错误说明)。"""
    payload = normalize_payload(data)
    error = validate_instance(payload, builtin_names=builtin_tool_names())
    if error:
        return None, error
    now = _now()
    config_json = _config_json(payload)
    async with get_db() as db:
        cursor = await db.execute(
            "SELECT id FROM tool_instances WHERE tool_name = ?",
            (payload["tool_name"],),
        )
        existing = await cursor.fetchone()
        if existing and existing["id"] != instance_id:
            return None, f"调用名 {payload['tool_name']} 已被使用。"
        if instance_id:
            cursor = await db.execute("SELECT id FROM tool_instances WHERE id = ?", (instance_id,))
            if await cursor.fetchone() is None:
                return None, "工具配置不存在。"
            await db.execute(
                "UPDATE tool_instances SET template = ?, display_name = ?, tool_name = ?, "
                "config_json = ?, updated_at = ? WHERE id = ?",
                (
                    TEMPLATE_ID,
                    payload["display_name"],
                    payload["tool_name"],
                    config_json,
                    now,
                    instance_id,
                ),
            )
        else:
            instance_id = uuid.uuid4().hex[:8]
            await db.execute(
                "INSERT INTO tool_instances "
                "(id, template, display_name, tool_name, config_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    instance_id,
                    TEMPLATE_ID,
                    payload["display_name"],
                    payload["tool_name"],
                    config_json,
                    now,
                    now,
                ),
            )
        await db.commit()
    saved = await get_tool_instance_by_id(instance_id)
    return saved, None


async def delete_tool_instance(instance_id: str) -> bool:
    async with get_db() as db:
        cursor = await db.execute("DELETE FROM tool_instances WHERE id = ?", (instance_id,))
        await db.commit()
        return cursor.rowcount > 0
