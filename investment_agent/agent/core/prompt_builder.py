"""System prompt 动态拼装 — 从 AgentEngine 中分离。

将基础 prompt + 项目路径 + 技能列表 + 委派策略的拼装逻辑
提取为独立类，职责单一且可独立测试。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...config import ROOT_DIR
from ..prompts import (
    MOUNTED_MARKER,
    PROJECT_PATH_MARKER,
    ROUTING_MARKER,
    SKILLS_MARKER,
    mounted_section,
    project_path_section,
    routing_section,
    skills_section,
)

if TYPE_CHECKING:
    from ...agent.skills.base import BaseSkill


class PromptBuilder:
    """System prompt 拼装器。"""

    def __init__(
        self,
        base_prompt: str,
        skills: list | None = None,
        delegation_tool_names: list[str] | None = None,
        mounted_subagents: list[dict] | None = None,
    ):
        self._base_prompt = base_prompt
        self._skills = skills or []
        self._delegation_tool_names = delegation_tool_names or []
        self._mounted_subagents = mounted_subagents or []

    def set_base_prompt(self, prompt: str) -> None:
        """更新基础 prompt（ContextManager 处理后调用）。"""
        self._base_prompt = prompt

    def set_skills(self, skills: list) -> None:
        """更新技能列表。"""
        self._skills = skills

    def build(self) -> str | list[dict]:
        """拼装完整 system prompt。"""
        prompt = self._base_prompt

        if isinstance(prompt, list):
            return prompt

        prompt = self._ensure_project_info(prompt)

        if self._mounted_subagents and MOUNTED_MARKER not in prompt:
            prompt += mounted_section([
                (sa.get("name", ""), sa.get("description") or "")
                for sa in self._mounted_subagents
            ])

        if self._delegation_tool_names and ROUTING_MARKER not in prompt:
            prompt += routing_section(", ".join(self._delegation_tool_names))

        if not self._skills:
            return prompt

        if SKILLS_MARKER in prompt:
            return prompt

        return prompt + skills_section(self._format_skills())

    def _ensure_project_info(self, prompt: str) -> str:
        if PROJECT_PATH_MARKER in prompt:
            return prompt

        return prompt + project_path_section(str(ROOT_DIR))

    def _format_skills(self) -> str:
        lines = []
        for s in self._skills:
            prefix = "[orch] " if s.skill_type == "orch" else ""
            deps = f"（含 {len(s.depends_on)} 个子流程）" if s.depends_on else ""
            lines.append(f"- {prefix}**{s.name}**: {s.description}{deps}")
        return "\n".join(lines)
