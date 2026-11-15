"""System prompt 动态拼装 — 从 AgentEngine 中分离。

将基础 prompt + 项目路径 + 技能列表 + 委派策略的拼装逻辑
提取为独立类，职责单一且可独立测试。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...agent.skills.base import BaseSkill


_ROUTING_STRATEGY = (
    "\n\n## 能力分层与委派策略\n"
    "- **Tools**：原子能力（读文件、搜索、执行命令）。简单取数/单次读写直接调用。\n"
    "- **Skills**：流程说明书。先调用 `Skill(name=...)` 加载说明，**下一轮**再按说明执行工具；"
    "同一步的多个 tool_calls 彼此看不到结果，不要同批「加载 Skill 又立刻按正文执行」。\n"
    "- **SubAgents（用户定义）**：隔离执行者。调用对应工具名，传入自包含的 `task`；"
    "适合多步、易污染主上下文的专项。同一 turn 可发起多个 SubAgent，前提是 task 互不依赖；"
    "完成后由你汇总。不要对同一目标重复委派。\n"
    "- **DelegateTask**：技能驱动的开放委派（编排/多 skill 流水线）。\n"
    "当前可用委派入口：{tool_names}。\n"
    "父 Agent 保留全局判断；简单场景直接用 Tools，无需委派。"
)


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

        if self._mounted_subagents and "## 已挂载 Subagent" not in prompt:
            prompt += self._format_mounted_subagents()

        if self._delegation_tool_names and "## 能力分层与委派策略" not in prompt:
            prompt += _ROUTING_STRATEGY.format(
                tool_names=", ".join(self._delegation_tool_names) or "(无)",
            )

        if not self._skills:
            return prompt

        if "# 可用技能" in prompt:
            return prompt

        return (
            prompt
            + "\n\n---\n\n# 可用技能\n\n"
            + self._format_skills()
            + "\n\n> 使用 Skill 工具加载技能完整说明后再执行。"
        )

    def _ensure_project_info(self, prompt: str) -> str:
        if "## 项目路径" in prompt:
            return prompt

        from ...config import ROOT_DIR

        return prompt + (
            f"\n\n## 项目路径\n\n"
            f"ROOT_DIR = {ROOT_DIR}\n"
        )

    def _format_skills(self) -> str:
        lines = []
        for s in self._skills:
            prefix = "[orch] " if s.skill_type == "orch" else ""
            deps = f"（含 {len(s.depends_on)} 个子流程）" if s.depends_on else ""
            lines.append(f"- {prefix}**{s.name}**: {s.description}{deps}")
        return "\n".join(lines)

    def _format_mounted_subagents(self) -> str:
        lines = ["\n\n## 已挂载 Subagent\n"]
        for sa in self._mounted_subagents:
            name = sa.get("name", "")
            desc = sa.get("description") or ""
            lines.append(f"- **{name}**: {desc}")
        lines.append(
            "\n调用时传入 `task`（可选 `expected_output`）；"
            "子 Agent 看不到主对话历史，仅返回最终摘要。"
        )
        lines.append(
            "\n委派约定：`task` 只写清输入路径、可选输出路径、股票代码/年份；"
            "**不要**在 task 里自拟 JSON schema、章节规则或手工扫描步骤"
            "（子 Agent 按挂载 skill/脚本执行，自拟格式易导致其空转超预算）。"
        )
        names = {sa.get("name", "") for sa in self._mounted_subagents}
        if "build_annual_report_index" in names:
            lines.append(
                "\n`build_annual_report_index` 示例 task：\n"
                "为 data/reports/md/002415/002415_2025年年度报告_2025.md 构建章节索引，"
                "输出到 data/reports/index/002415_2025年年度报告_index.json。"
                "expected_output 仅写「索引已写入上述路径 + 一级/二级章节数量摘要」。"
            )
        return "\n".join(lines)
