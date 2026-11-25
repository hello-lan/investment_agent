"""内置 Subagent：从本地 Markdown 目录只读加载到内存，不入库。"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from ...agent.core.subagent_config import extract_runtime_config_from_frontmatter
from ...config import resolve_subagents_dir
from ..db import get_db

logger = logging.getLogger(__name__)

BUILTIN_ID_PREFIX = "builtin:"

_FRONTMATTER_RE = re.compile(
    r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$",
)

# 按 id 索引的内置定义；启动时由 load_builtin_subagents 填充
_BUILTIN_BY_ID: dict[str, dict] = {}
# name → id
_BUILTIN_NAME_TO_ID: dict[str, str] = {}


def builtin_id_for_name(name: str) -> str:
    return f"{BUILTIN_ID_PREFIX}{name.strip()}"


def is_builtin_id(subagent_id: str | None) -> bool:
    return bool(subagent_id) and str(subagent_id).startswith(BUILTIN_ID_PREFIX)


def list_builtins() -> list[dict]:
    """返回内置 Subagent 列表（按 name 排序）。"""
    items = list(_BUILTIN_BY_ID.values())
    items.sort(key=lambda x: (x.get("name") or "").lower())
    return [dict(item) for item in items]


def builtin_names() -> set[str]:
    return set(_BUILTIN_NAME_TO_ID.keys())


def get_builtin(subagent_id_or_name: str | None) -> dict | None:
    """按 id（builtin:name）或 name 查找内置定义。"""
    if not subagent_id_or_name:
        return None
    key = str(subagent_id_or_name).strip()
    if key in _BUILTIN_BY_ID:
        return dict(_BUILTIN_BY_ID[key])
    builtin_id = _BUILTIN_NAME_TO_ID.get(key)
    if builtin_id:
        return dict(_BUILTIN_BY_ID[builtin_id])
    return None


def _unquote_yaml_scalar(raw: str) -> str:
    text = str(raw or "").strip()
    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        if text.startswith('"'):
            try:
                return json.loads(text)
            except (TypeError, ValueError, json.JSONDecodeError):
                pass
        return text[1:-1]
    return text


def _parse_csv_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    text = str(raw).strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    result: list[str] = []
    for part in text.split(","):
        item = part.strip().strip("'\"")
        if item:
            result.append(item)
    return result


def parse_subagent_markdown(text: str) -> dict:
    """解析与 UI formatSubagentMarkdown 对齐的 Markdown。"""
    cleaned = str(text or "").lstrip("\ufeff")
    match = _FRONTMATTER_RE.match(cleaned)
    if not match:
        raise ValueError("Markdown 需包含 YAML frontmatter（以 --- 包裹）")

    front, body = match.group(1), match.group(2) or ""
    fields: dict[str, str] = {}
    for line in front.splitlines():
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if not m:
            continue
        fields[m.group(1).lower()] = _unquote_yaml_scalar(m.group(2))

    return {
        "name": fields.get("name", ""),
        "description": fields.get("description", ""),
        "tools": _parse_csv_list(fields.get("tools")),
        "skills": _parse_csv_list(fields.get("skills")),
        "model_id": (fields.get("model") or fields.get("model_id") or "").strip(),
        "runtime_config": extract_runtime_config_from_frontmatter(fields),
        "system_prompt": body.lstrip("\r\n"),
    }


def discover_default_subagents(directory: Path) -> list[Path]:
    """扫描目录下的 *.md，忽略点开头文件。"""
    if not directory.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(directory.glob("*.md")):
        if path.name.startswith("."):
            continue
        if path.is_file():
            files.append(path)
    return files


def _build_builtin_entry(parsed: dict) -> dict:
    name = (parsed.get("name") or "").strip()
    return {
        "id": builtin_id_for_name(name),
        "name": name,
        "description": parsed.get("description") or "",
        "system_prompt": parsed.get("system_prompt") or "",
        "model_id": parsed.get("model_id") or "",
        "tools": list(parsed.get("tools") or []),
        "skills": list(parsed.get("skills") or []),
        "runtime_config": dict(parsed.get("runtime_config") or {}),
        "builtin": True,
        "created_at": None,
        "updated_at": None,
    }


async def load_builtin_subagents(directory: Path | None = None) -> dict:
    """启动时只读加载内置 Subagent 到内存，不写数据库。"""
    from .subagent_service import SubagentService

    global _BUILTIN_BY_ID, _BUILTIN_NAME_TO_ID
    _BUILTIN_BY_ID = {}
    _BUILTIN_NAME_TO_ID = {}

    base = directory or resolve_subagents_dir()
    stats = {"loaded": 0, "failed": 0}

    if not base.exists():
        base.mkdir(parents=True, exist_ok=True)
        logger.info("内置 Subagent 目录不存在，已创建: %s", base)
        return stats

    for path in discover_default_subagents(base):
        try:
            text = path.read_text(encoding="utf-8")
            parsed = parse_subagent_markdown(text)
            name = (parsed.get("name") or "").strip()
            err = SubagentService.validate_name(name)
            if err:
                raise ValueError(err)
            if not (parsed.get("description") or "").strip():
                raise ValueError("description 不能为空")
            if not (parsed.get("system_prompt") or "").strip():
                raise ValueError("system_prompt（Markdown body）不能为空")
            if name in _BUILTIN_NAME_TO_ID:
                raise ValueError(f"内置 name '{name}' 重复（{path.name}）")

            entry = _build_builtin_entry(parsed)
            _BUILTIN_BY_ID[entry["id"]] = entry
            _BUILTIN_NAME_TO_ID[name] = entry["id"]
            stats["loaded"] += 1
            logger.info("已加载内置 Subagent: %s (%s)", name, path.name)
        except Exception as exc:
            stats["failed"] += 1
            logger.warning("加载内置 Subagent 失败 %s: %s", path.name, exc)

    logger.info(
        "内置 Subagent 加载完成: loaded=%s failed=%s",
        stats["loaded"],
        stats["failed"],
    )
    return stats


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


async def migrate_seeded_builtins() -> dict:
    """将历史 seed 进库的同名 Subagent 迁移为内置 ID，并删除 DB 行。"""
    from .subagent_service import SubagentService

    stats = {"remapped": 0, "deleted": 0, "agents_updated": 0}
    if not _BUILTIN_BY_ID:
        return stats

    remaps: list[tuple[str, str, str]] = []
    for name, builtin_id in _BUILTIN_NAME_TO_ID.items():
        existing = await SubagentService.get_by_name_db_only(name)
        if not existing:
            continue
        old_id = existing["id"]
        remaps.append((name, old_id, builtin_id))

    if not remaps:
        return stats

    id_map = {old_id: new_id for _, old_id, new_id in remaps}

    async with get_db() as db:
        cursor = await db.execute("SELECT id, name, subagents FROM agents")
        agent_rows = await cursor.fetchall()

        for row in agent_rows:
            ids = _parse_json_list(row["subagents"])
            if not ids:
                continue
            changed = False
            new_ids: list[str] = []
            seen: set[str] = set()
            for sid in ids:
                mapped = id_map.get(sid, sid)
                if mapped != sid:
                    changed = True
                if mapped in seen:
                    continue
                seen.add(mapped)
                new_ids.append(mapped)
            if changed:
                await db.execute(
                    "UPDATE agents SET subagents=? WHERE id=?",
                    (json.dumps(new_ids, ensure_ascii=False), row["id"]),
                )
                stats["agents_updated"] += 1
                stats["remapped"] += 1
                logger.info(
                    "已迁移 Agent %s 的 Subagent 挂载到内置 ID",
                    row["name"],
                )

        for name, old_id, _builtin_id in remaps:
            await db.execute("DELETE FROM subagents WHERE id = ?", (old_id,))
            stats["deleted"] += 1
            logger.info("已删除历史 seed Subagent: %s (%s)", name, old_id)

        await db.commit()

    logger.info(
        "内置 Subagent 迁移完成: agents_updated=%s deleted=%s",
        stats["agents_updated"],
        stats["deleted"],
    )
    return stats
