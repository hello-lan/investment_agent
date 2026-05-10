from pathlib import Path

from ...config import get_settings, PROJECT_ROOT
from .base import BaseSkill
from .markdown_parser import parse_skill_markdown
from .markdown_skill import MarkdownSkill

_registry: dict[str, BaseSkill] = {}


def _register(skill: BaseSkill) -> None:
    _registry[skill.name] = skill


def _project_root() -> Path:
    return PROJECT_ROOT


def _resolve_skills_directory() -> Path:
    settings = get_settings()
    skills_cfg = settings.get("skills", {}) if isinstance(settings.get("skills", {}), dict) else {}
    raw_dir = str(skills_cfg.get("directory", "./skills")).strip() or "./skills"
    path = Path(raw_dir)
    if not path.is_absolute():
        path = _project_root() / path
    return path


def _discover_markdown_files(base_dir: Path) -> list[Path]:
    if not base_dir.exists() or not base_dir.is_dir():
        return []

    found: list[Path] = []
    for child in base_dir.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        skill_md = child / "skill.md"
        readme_md = child / "README.md"
        if skill_md.exists() and skill_md.is_file():
            found.append(skill_md)
        elif readme_md.exists() and readme_md.is_file():
            found.append(readme_md)
    return found


def reload_skills() -> None:
    _registry.clear()
    skills_dir = _resolve_skills_directory()
    for md_file in _discover_markdown_files(skills_dir):
        try:
            parsed = parse_skill_markdown(md_file)
            _register(MarkdownSkill(parsed))
        except Exception:
            continue


reload_skills()


def get_all_skills() -> list[BaseSkill]:
    return list(_registry.values())


def get_skill(name: str) -> BaseSkill | None:
    return _registry.get(name)


def get_schemas(skill_names: list[str] | None = None) -> list[dict]:
    if not skill_names:
        return [s.schema for s in _registry.values()]
    wanted = set(skill_names)
    return [s.schema for s in _registry.values() if s.name in wanted]
