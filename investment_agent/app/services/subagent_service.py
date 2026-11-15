"""Subagent 定义服务层 — CRUD 与挂载校验。"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

from ..db import get_db

# 合法工具名：字母开头，字母数字下划线，2-64 字符
_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{1,63}$")

# 禁止与内置工具冲突
RESERVED_TOOL_NAMES = frozenset({
    "Skill",
    "run_command",
    "DelegateTask",
    "Subagent",
    "list_files",
    "read_file",
    "search_text",
    "write_file",
    "run_python_script",
})

# Subagent 自身不可挂载的委派类工具
FORBIDDEN_SUBAGENT_TOOLS = frozenset({
    "DelegateTask",
    "Subagent",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_json_list(raw) -> list:
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    try:
        value = json.loads(raw)
        return value if isinstance(value, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def _row_to_dict(row) -> dict:
    d = dict(row)
    d["tools"] = _parse_json_list(d.get("tools"))
    d["skills"] = _parse_json_list(d.get("skills"))
    d["model_id"] = d.get("model_id") or ""
    return d


class SubagentService:
    """用户定义 Subagent CRUD。"""

    @staticmethod
    def validate_name(name: str) -> str | None:
        """返回错误信息，合法则返回 None。"""
        if not name or not name.strip():
            return "name 不能为空"
        name = name.strip()
        if not _NAME_RE.match(name):
            return "name 须匹配 ^[a-zA-Z][a-zA-Z0-9_]{1,63}$"
        if name in RESERVED_TOOL_NAMES:
            return f"name '{name}' 与内置工具冲突"
        return None

    @staticmethod
    def sanitize_tools(tools: list[str] | None) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for t in tools or []:
            name = str(t).strip()
            if not name or name in FORBIDDEN_SUBAGENT_TOOLS or name in seen:
                continue
            seen.add(name)
            result.append(name)
        return result

    @staticmethod
    def sanitize_skills(skills: list[str] | None) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for s in skills or []:
            name = str(s).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            result.append(name)
        return result

    @staticmethod
    async def list_subagents() -> list[dict]:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT id, name, description, system_prompt, model_id, "
                "tools, skills, created_at, updated_at "
                "FROM subagents ORDER BY created_at"
            )
            rows = await cursor.fetchall()
        return [_row_to_dict(r) for r in rows]

    @staticmethod
    async def get_subagent(subagent_id: str) -> dict | None:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM subagents WHERE id = ?", (subagent_id,)
            )
            row = await cursor.fetchone()
        return _row_to_dict(row) if row else None

    @staticmethod
    async def get_by_name(name: str) -> dict | None:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM subagents WHERE name = ?", (name,)
            )
            row = await cursor.fetchone()
        return _row_to_dict(row) if row else None

    @staticmethod
    async def get_by_ids(ids: list[str]) -> list[dict]:
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        async with get_db() as db:
            cursor = await db.execute(
                f"SELECT * FROM subagents WHERE id IN ({placeholders})",
                tuple(ids),
            )
            rows = await cursor.fetchall()
        by_id = {}
        for r in rows:
            d = _row_to_dict(r)
            by_id[d["id"]] = d
        # 保持挂载顺序
        return [by_id[i] for i in ids if i in by_id]

    @staticmethod
    async def create_subagent(
        name: str,
        description: str = "",
        system_prompt: str = "",
        model_id: str = "",
        tools: list[str] | None = None,
        skills: list[str] | None = None,
    ) -> str:
        err = SubagentService.validate_name(name)
        if err:
            raise ValueError(err)

        name = name.strip()
        existing = await SubagentService.get_by_name(name)
        if existing:
            raise ValueError(f"name '{name}' 已存在")

        subagent_id = str(uuid.uuid4())[:8]
        now = _now()
        async with get_db() as db:
            await db.execute(
                "INSERT INTO subagents (id, name, description, system_prompt, "
                "model_id, tools, skills, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    subagent_id,
                    name,
                    description or "",
                    system_prompt or "",
                    model_id or "",
                    json.dumps(SubagentService.sanitize_tools(tools)),
                    json.dumps(SubagentService.sanitize_skills(skills)),
                    now,
                    now,
                ),
            )
            await db.commit()
        return subagent_id

    @staticmethod
    async def update_subagent(
        subagent_id: str,
        name: str,
        description: str = "",
        system_prompt: str = "",
        model_id: str = "",
        tools: list[str] | None = None,
        skills: list[str] | None = None,
    ) -> bool:
        err = SubagentService.validate_name(name)
        if err:
            raise ValueError(err)

        name = name.strip()
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT id FROM subagents WHERE id = ?", (subagent_id,)
            )
            if not await cursor.fetchone():
                return False

            cursor = await db.execute(
                "SELECT id FROM subagents WHERE name = ? AND id != ?",
                (name, subagent_id),
            )
            if await cursor.fetchone():
                raise ValueError(f"name '{name}' 已存在")

            await db.execute(
                "UPDATE subagents SET name=?, description=?, system_prompt=?, "
                "model_id=?, tools=?, skills=?, updated_at=? WHERE id=?",
                (
                    name,
                    description or "",
                    system_prompt or "",
                    model_id or "",
                    json.dumps(SubagentService.sanitize_tools(tools)),
                    json.dumps(SubagentService.sanitize_skills(skills)),
                    _now(),
                    subagent_id,
                ),
            )
            await db.commit()
        return True

    @staticmethod
    async def find_agents_mounting(subagent_id: str) -> list[dict]:
        """返回挂载了该 subagent 的主 Agent 列表。"""
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT id, name, subagents FROM agents"
            )
            rows = await cursor.fetchall()
        mounted = []
        for row in rows:
            ids = _parse_json_list(row["subagents"])
            if subagent_id in ids:
                mounted.append({"id": row["id"], "name": row["name"]})
        return mounted

    @staticmethod
    async def delete_subagent(subagent_id: str) -> None:
        mounted = await SubagentService.find_agents_mounting(subagent_id)
        if mounted:
            names = ", ".join(a["name"] for a in mounted)
            raise ValueError(
                f"仍被以下 Agent 挂载，无法删除: {names}"
            )
        async with get_db() as db:
            await db.execute("DELETE FROM subagents WHERE id = ?", (subagent_id,))
            await db.commit()
