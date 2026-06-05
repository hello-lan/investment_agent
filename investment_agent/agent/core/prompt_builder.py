"""System prompt 动态拼装 — 从 AgentEngine 中分离。

将基础 prompt + 项目路径 + 技能列表 + 委派策略的拼装逻辑
提取为独立类，职责单一且可独立测试。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...agent.skills.base import BaseSkill


_DELEGATION_STRATEGY = (
    "\n\n## 子任务委派策略\n"
    "加载技能说明后，分析其工作流程是否包含互不依赖的子阶段。若技能明确分为多个独立分析维度"
    "应使用 DelegateTask 将各维度委派给子Agent逐个执行。"
    "父Agent保留全局判断（交叉验证、综合定级），子Agent返回结果后汇总整合。"
    "简单场景（如仅查单一指标）直接执行，无需委派。"
)


class PromptBuilder:
    """System prompt 拼装器。

    将基础 prompt 与项目路径、技能描述、委派策略组合，
    生成供 LLM 使用的完整 system prompt。

    幂等性：多次调用 build() 返回相同结果。
    """

    def __init__(self, base_prompt: str, skills: list | None = None):
        self._base_prompt = base_prompt
        self._skills = skills or []

    def set_base_prompt(self, prompt: str) -> None:
        """更新基础 prompt（ContextManager 处理后调用）。"""
        self._base_prompt = prompt

    def set_skills(self, skills: list) -> None:
        """更新技能列表。"""
        self._skills = skills

    def build(self) -> str | list[dict]:
        """拼装完整 system prompt。

        若 base_prompt 已是 list[dict]（Anthropic cache_control 格式），
        直接返回，不做额外拼装。
        """
        prompt = self._base_prompt

        # ContextManager 已处理为带 cache_control 的 content block 列表
        if isinstance(prompt, list):
            return prompt

        prompt = self._ensure_project_info(prompt)

        if not self._skills:
            return prompt

        if "# 可用技能" in prompt:
            return prompt

        return (
            prompt
            + "\n\n---\n\n# 可用技能\n\n"
            + self._format_skills()
            + "\n\n> 使用 Skill 工具加载技能完整说明后再执行。"
            + _DELEGATION_STRATEGY
        )

    def _ensure_project_info(self, prompt: str) -> str:
        """确保 prompt 包含项目路径。"""
        if "## 项目路径" in prompt:
            return prompt

        from ...config import PROJECT_ROOT

        return prompt + (
            f"\n\n## 项目路径\n\n"
            f"PROJECT_ROOT = {PROJECT_ROOT}\n"
        )

    def _format_skills(self) -> str:
        """格式化技能列表为 Markdown。"""
        lines = []
        for s in self._skills:
            prefix = "[orch] " if s.skill_type == "orch" else ""
            deps = f"（含 {len(s.depends_on)} 个子流程）" if s.depends_on else ""
            lines.append(f"- {prefix}**{s.name}**: {s.description}{deps}")
        return "\n".join(lines)
