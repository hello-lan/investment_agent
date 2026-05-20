from pathlib import Path

from .base import BaseSkill
from .markdown_parser import parse_skill_markdown
from .markdown_skill import MarkdownSkill

# Skill 注册中心
_registry: dict[str, BaseSkill] = {}
_skills_dir: Path | None = None


def _register(skill: BaseSkill) -> None:
    _registry[skill.name] = skill


def init_skills_dir(dir_path: Path) -> None:
    """设置 Skills 目录并执行初始加载。由 app 层在启动时调用。"""
    global _skills_dir
    _skills_dir = dir_path
    reload_skills()


def _discover_markdown_files(base_dir: Path) -> list[Path]:
    """扫描目录：每个子目录下的 SKILL.md 文件即为一个 Skill 定义"""
    if not base_dir.exists() or not base_dir.is_dir():
        return []

    found: list[Path] = []
    for child in base_dir.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue

        files = {p.name: p for p in child.iterdir() if p.is_file()}
        skill_md = files.get("SKILL.md")
        if skill_md:
            found.append(skill_md)
    return found


def reload_skills() -> None:
    """清空并重新扫描 Skills 目录，重新加载所有 Skill"""
    _registry.clear()
    if _skills_dir:
        for md_file in _discover_markdown_files(_skills_dir):
            try:
                parsed = parse_skill_markdown(md_file)
                _register(MarkdownSkill(parsed))
            except Exception:
                continue


def get_all_skills() -> list[BaseSkill]:
    reload_skills()
    return list(_registry.values())


def get_skill(name: str) -> BaseSkill | None:
    return _registry.get(name)


def get_schemas(skill_names: list[str] | None = None) -> list[dict]:
    """返回 Skill 的 Anthropic tool schema 列表，用于注入 system prompt"""
    if not skill_names:
        return [s.schema for s in _registry.values()]
    wanted = set(skill_names)
    return [s.schema for s in _registry.values() if s.name in wanted]
