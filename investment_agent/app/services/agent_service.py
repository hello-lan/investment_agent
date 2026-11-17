"""Agent 配置服务层 — 封装 agents 相关的所有 DB 操作。

从 app/api/agents.py 提取，分离 HTTP 路由与数据访问逻辑。
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ...config import ROOT_DIR
from ..db import get_db

AVATARS_DIR = ROOT_DIR / "data" / "avatars"
ALLOWED_AVATAR_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_AVATAR_BYTES = 2 * 1024 * 1024
_AGENT_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


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


def _remove_avatar_files(agent_id: str, keep_ext: str | None = None) -> None:
    """删除该 Agent 的头像文件。keep_ext 指定要保留的扩展名。"""
    if not _AGENT_ID_RE.fullmatch(agent_id or ""):
        return
    for ext in ALLOWED_AVATAR_EXTS:
        if keep_ext and ext == keep_ext:
            continue
        path = AVATARS_DIR / f"{agent_id}{ext}"
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            continue


def _normalize_avatar(agent_id: str, avatar: str | None) -> str:
    """只接受 avatars/{agent_id}{ext}，其余一律视为未设置。"""
    raw = (avatar or "").strip().replace("\\", "/")
    if not raw or not _AGENT_ID_RE.fullmatch(agent_id or ""):
        return ""
    for ext in ALLOWED_AVATAR_EXTS:
        if raw == f"avatars/{agent_id}{ext}":
            return raw
    return ""


def _looks_like_image(content: bytes, ext: str) -> bool:
    if ext == ".png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if ext in {".jpg", ".jpeg"}:
        return content.startswith(b"\xff\xd8\xff")
    if ext == ".gif":
        return content.startswith((b"GIF87a", b"GIF89a"))
    if ext == ".webp":
        return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    return False


def _row_to_agent(row) -> dict:
    d = dict(row)
    d["skills"] = _parse_json_list(d.get("skills"))
    d["tools"] = _parse_json_list(d.get("tools"))
    d["subagents"] = _parse_json_list(d.get("subagents"))
    return d


class AgentService:
    """Agent 配置 CRUD。"""

    @staticmethod
    async def list_agents() -> list[dict]:
        """获取所有 Agent 配置列表。"""
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT id, name, description, system_prompt, model_id, "
                "temperature, max_single_turn_output_tokens, skills, tools, subagents, "
                "compress_config, engine_config, avatar, created_at, updated_at "
                "FROM agents ORDER BY created_at"
            )
            rows = await cursor.fetchall()
        return [_row_to_agent(r) for r in rows]

    @staticmethod
    async def create_agent(
        name: str,
        description: str = "",
        system_prompt: str = "",
        model_id: str = "",
        temperature: float = 0.7,
        max_single_turn_output_tokens: int = 4096,
        skills: list[str] | None = None,
        tools: list[str] | None = None,
        subagents: list[str] | None = None,
        compress_config: dict | None = None,
        engine_config: dict | None = None,
        avatar: str = "",
    ) -> str:
        """创建新 Agent，返回 agent_id。"""
        agent_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()
        stored_avatar = _normalize_avatar(agent_id, avatar)
        async with get_db() as db:
            await db.execute(
                "INSERT INTO agents (id, name, description, system_prompt, "
                "model_id, temperature, max_single_turn_output_tokens, skills, tools, subagents, "
                "compress_config, engine_config, avatar, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    agent_id, name, description, system_prompt,
                    model_id, temperature, max_single_turn_output_tokens,
                    json.dumps(skills or []),
                    json.dumps(tools or []),
                    json.dumps(subagents or []),
                    json.dumps(compress_config) if compress_config is not None else None,
                    json.dumps(engine_config) if engine_config is not None else None,
                    stored_avatar or None,
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
            return _row_to_agent(agent) if agent else None

    @staticmethod
    async def update_agent(
        agent_id: str,
        name: str,
        description: str = "",
        system_prompt: str = "",
        model_id: str = "",
        temperature: float = 0.7,
        max_single_turn_output_tokens: int = 4096,
        skills: list[str] | None = None,
        tools: list[str] | None = None,
        subagents: list[str] | None = None,
        compress_config: dict | None = None,
        engine_config: dict | None = None,
        avatar: str = "",
    ) -> bool:
        """更新 Agent 配置，返回是否成功（False = 不存在）。"""
        now = datetime.now(timezone.utc).isoformat()
        stored_avatar = _normalize_avatar(agent_id, avatar)
        async with get_db() as db:
            row = await db.execute(
                "SELECT id FROM agents WHERE id = ?", (agent_id,)
            )
            if not await row.fetchone():
                return False

            await db.execute(
                "UPDATE agents SET name=?, description=?, system_prompt=?, "
                "model_id=?, temperature=?, max_single_turn_output_tokens=?, skills=?, tools=?, "
                "subagents=?, compress_config=?, engine_config=?, avatar=?, updated_at=? "
                "WHERE id=?",
                (
                    name, description, system_prompt,
                    model_id, temperature, max_single_turn_output_tokens,
                    json.dumps(skills or []),
                    json.dumps(tools or []),
                    json.dumps(subagents or []),
                    json.dumps(compress_config) if compress_config is not None else None,
                    json.dumps(engine_config) if engine_config is not None else None,
                    stored_avatar or None,
                    now, agent_id,
                ),
            )
            await db.commit()
        keep_ext = Path(stored_avatar).suffix.lower() if stored_avatar else None
        _remove_avatar_files(agent_id, keep_ext=keep_ext)
        return True

    @staticmethod
    async def save_avatar(agent_id: str, filename: str, content: bytes) -> str | None:
        """写入头像文件并更新 avatar 字段。Agent 不存在时返回 None。"""
        if not _AGENT_ID_RE.fullmatch(agent_id or ""):
            raise ValueError("无效的 Agent ID")
        ext = Path(filename or "").suffix.lower()
        if ext not in ALLOWED_AVATAR_EXTS:
            raise ValueError(f"不支持的文件类型: {ext or 'unknown'}")
        if len(content) > MAX_AVATAR_BYTES:
            raise ValueError("头像过大，最大支持 2MB")
        if not _looks_like_image(content, ext):
            raise ValueError("文件内容与扩展名不符")

        async with get_db() as db:
            row = await db.execute(
                "SELECT id FROM agents WHERE id = ?", (agent_id,)
            )
            if not await row.fetchone():
                return None

        AVATARS_DIR.mkdir(parents=True, exist_ok=True)
        dest = AVATARS_DIR / f"{agent_id}{ext}"
        dest.write_bytes(content)
        _remove_avatar_files(agent_id, keep_ext=ext)

        rel = f"avatars/{agent_id}{ext}"
        now = datetime.now(timezone.utc).isoformat()
        async with get_db() as db:
            await db.execute(
                "UPDATE agents SET avatar=?, updated_at=? WHERE id=?",
                (rel, now, agent_id),
            )
            await db.commit()
        return rel

    @staticmethod
    async def delete_agent(agent_id: str) -> None:
        """删除 Agent 配置及其头像文件。"""
        async with get_db() as db:
            await db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
            await db.commit()
        _remove_avatar_files(agent_id)
