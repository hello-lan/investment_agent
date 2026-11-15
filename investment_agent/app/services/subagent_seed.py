"""默认 Subagent 启动导入：从本地 Markdown 目录按 name 仅插入缺失项。"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ...agent.core.subagent_config import extract_runtime_config_from_frontmatter
from ...config import resolve_subagents_dir
from .subagent_service import SubagentService

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(
    r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$",
)


def _unquote_yaml_scalar(raw: str) -> str:
    text = str(raw or "").strip()
    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        if text.startswith('"'):
            try:
                import json

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


def _needs_refresh(existing: dict, parsed: dict) -> bool:
    """本地 Markdown 与 DB 记录是否不一致（默认 Subagent 以 md 为准刷新）。"""
    fields = (
        ("description", parsed.get("description") or ""),
        ("system_prompt", parsed.get("system_prompt") or ""),
    )
    for key, want in fields:
        if (existing.get(key) or "") != want:
            return True
    want_tools = parsed.get("tools") or []
    want_skills = parsed.get("skills") or []
    if list(existing.get("tools") or []) != list(want_tools):
        return True
    if list(existing.get("skills") or []) != list(want_skills):
        return True
    want_runtime = parsed.get("runtime_config") or {}
    have_runtime = existing.get("runtime_config") or {}
    if dict(have_runtime) != dict(want_runtime):
        return True
    return False


async def seed_default_subagents(directory: Path | None = None) -> dict:
    """启动时导入默认 Subagent：同名不存在则创建；已存在但与 md 不一致则刷新。"""
    base = directory or resolve_subagents_dir()
    stats = {"imported": 0, "updated": 0, "skipped": 0, "failed": 0}

    if not base.exists():
        base.mkdir(parents=True, exist_ok=True)
        logger.info("默认 Subagent 目录不存在，已创建: %s", base)
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

            existing = await SubagentService.get_by_name(name)
            if existing:
                if not _needs_refresh(existing, parsed):
                    stats["skipped"] += 1
                    logger.debug("跳过已同步 Subagent: %s (%s)", name, path.name)
                    continue
                await SubagentService.update_subagent(
                    existing["id"],
                    name=name,
                    description=parsed["description"],
                    system_prompt=parsed["system_prompt"],
                    model_id=parsed.get("model_id") or existing.get("model_id") or "",
                    tools=parsed.get("tools") or [],
                    skills=parsed.get("skills") or [],
                    runtime_config=parsed.get("runtime_config") or {},
                )
                stats["updated"] += 1
                logger.info("已刷新默认 Subagent: %s (%s)", name, path.name)
                continue

            await SubagentService.create_subagent(
                name=name,
                description=parsed["description"],
                system_prompt=parsed["system_prompt"],
                model_id=parsed.get("model_id") or "",
                tools=parsed.get("tools") or [],
                skills=parsed.get("skills") or [],
                runtime_config=parsed.get("runtime_config") or {},
            )
            stats["imported"] += 1
            logger.info("已导入默认 Subagent: %s (%s)", name, path.name)
        except Exception as exc:
            stats["failed"] += 1
            logger.warning("导入默认 Subagent 失败 %s: %s", path.name, exc)

    logger.info(
        "默认 Subagent 导入完成: imported=%s updated=%s skipped=%s failed=%s",
        stats["imported"],
        stats["updated"],
        stats["skipped"],
        stats["failed"],
    )
    return stats
