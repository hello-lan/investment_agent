"""Agent 注册容器 — 封装工具和技能的注册，替代全局 _tool_registry / _registry。

在 AgentRunner 中按需创建实例并注入到 Engine，消除全局可变状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .tools.base import BaseTool
    from .skills.base import BaseSkill


@dataclass
class AgentRegistry:
    """工具和技能的注册中心，替代全局单例注册表。

    每个 Agent 会话拥有独立的 Registry 实例，避免跨会话状态污染。
    """

    tools: dict[str, "BaseTool"] = field(default_factory=dict)
    skills: dict[str, "BaseSkill"] = field(default_factory=dict)
    auto_bound_tools: set[str] = field(default_factory=lambda: {"Skill", "run_command", "DelegateTask"})

    # ── Tool registration ──────────────────────────────────────────────

    def register_tool(self, instance: "BaseTool") -> None:
        """编目工具实例。"""
        self.tools[instance.name] = instance

    def get_tool(self, name: str) -> "BaseTool | None":
        """按名称查找工具。"""
        return self.tools.get(name)

    def get_all_tool_infos(self) -> list[dict]:
        """返回所有已编目工具的元信息（供前端展示）。"""
        return [
            {
                "name": t.name,
                "description": t.description,
                "auto_bound": t.name in self.auto_bound_tools,
            }
            for t in self.tools.values()
        ]

    def get_schemas_for_names(self, names: set[str]) -> list[dict]:
        """返回指定名称的工具 Anthropic tool schema。"""
        return [t.schema for t in self.tools.values() if t.name in names]

    def bootstrap_default_tools(self) -> None:
        """导入并编目默认工具（替代 registry.py 的模块级 import）。"""
        from .tools.run_command import RunCommandTool
        from .tools.delegate_task import DelegateTaskTool
        from .tools.skill_tool import SkillTool
        self.register_tool(SkillTool())
        self.register_tool(RunCommandTool())
        self.register_tool(DelegateTaskTool())

    # ── Skill registration ─────────────────────────────────────────────

    def register_skill(self, skill: "BaseSkill") -> None:
        """编目技能。"""
        self.skills[skill.name] = skill

    def get_skill(self, name: str) -> "BaseSkill | None":
        """按名称查找技能。"""
        return self.skills.get(name)

    def get_all_skills(self) -> list["BaseSkill"]:
        """返回所有已编目技能。"""
        return list(self.skills.values())

    def get_schemas(self, skill_names: list[str] | None = None) -> list[dict]:
        """返回 Anthropic tool schema 列表（含依赖展开）。

        Args:
            skill_names: 指定技能名，None 返回全部。
        """
        if not skill_names:
            return [s.schema for s in self.skills.values()]
        from .skills.dependency import expand_with_dependencies
        wanted = set(expand_with_dependencies(skill_names))
        return [s.schema for s in self.skills.values() if s.name in wanted]

    def reload_skills(self, skills_dir: Path) -> None:
        """扫描目录并重新加载所有 SKILL.md 定义的技能。"""
        from .skills.loader import _discover_markdown_files
        from .skills.markdown_parser import parse_skill_markdown
        from .skills.markdown_skill import MarkdownSkill
        from .skills.dependency import validate_dependencies
        import logging
        _log = logging.getLogger(__name__)

        self.skills.clear()
        if not skills_dir.exists() or not skills_dir.is_dir():
            return

        for md_file in _discover_markdown_files(skills_dir):
            try:
                parsed = parse_skill_markdown(md_file)
                self.register_skill(MarkdownSkill(parsed))
            except Exception:
                continue

        for warning in validate_dependencies(dict(self.skills)):
            _log.warning("Skill dependency: %s", warning)
