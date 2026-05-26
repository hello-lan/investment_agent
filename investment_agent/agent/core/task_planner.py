"""委派任务指令生成器。

基于父Agent的对话上下文，为子Agent生成聚焦的任务指令。
从 engine.py 中拆分，与引擎主循环解耦。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..config import TASK_PLANNER_SYSTEM, TASK_PLANNER_PROMPT

if TYPE_CHECKING:
    from .models import ModelProvider

_log = logging.getLogger(__name__)


def extract_text_from_content(content) -> str:
    """从 Anthropic content blocks 中提取纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "reasoning":
                    parts.append(block.get("content", ""))
        return "\n".join(parts)
    return str(content)


class TaskPlanner:
    """委派任务指令生成器。

    使用轻量 LLM 调用提炼父Agent的对话上下文，生成适合子Agent的任务说明。
    失败时 fallback 到 LLM 传入的原始 task 描述。
    """

    def __init__(
        self,
        provider: "ModelProvider",
        temperature: float | None = None,
        max_tokens: int | None = None,
        planning_max_tokens: int = 512,
        skill_body_max_chars: int = 3000,
    ):
        self.provider = provider
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.planning_max_tokens = planning_max_tokens
        self.skill_body_max_chars = skill_body_max_chars
        # token 消耗回写到调用方
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    async def generate(
        self,
        task: str,
        skill_names: list[str],
        parent_messages: list[dict],
    ) -> str:
        """基于父Agent对话上下文生成子Agent任务指令。

        Args:
            task: 父Agent的原始任务描述
            skill_names: 子Agent将使用的技能列表
            parent_messages: 父Agent的当前消息列表

        Returns:
            生成的任务指令，失败时返回原始 task
        """
        if not parent_messages:
            return task

        from ...config import PROJECT_ROOT

        text_messages = self._build_text_messages(parent_messages)
        skill_info = self._build_skill_info(skill_names)
        prompt = TASK_PLANNER_PROMPT.format(
            task=task, skill_info=skill_info, project_root=PROJECT_ROOT
        )
        text_messages.append({"role": "user", "content": prompt})

        try:
            kwargs: dict = {
                "messages": text_messages,
                "system": TASK_PLANNER_SYSTEM,
            }
            if self.temperature is not None:
                kwargs["temperature"] = self.temperature
            if self.max_tokens is not None:
                kwargs["max_tokens"] = min(self.max_tokens, self.planning_max_tokens)
            else:
                kwargs["max_tokens"] = self.planning_max_tokens
            resp = await self.provider.chat(**kwargs)
            self.total_input_tokens += resp.input_tokens
            self.total_output_tokens += resp.output_tokens
            if resp.content:
                return resp.content.strip()
        except Exception:
            _log.warning("Task instruction generation failed, using fallback", exc_info=True)

        return task

    def _build_text_messages(self, parent_messages: list[dict]) -> list[dict]:
        """构建精简纯文本消息：提取文本内容，丢弃 tool_use/tool_result blocks。

        避免 OpenAI 兼容 Provider 因 tool pair 不完整而报错 (400 Bad Request)。
        取首条用户问题 + 最近5条（去重避免重叠）。
        """
        def _msg_text(msg: dict) -> dict | None:
            role = msg.get("role", "")
            text = extract_text_from_content(msg.get("content", ""))
            return {"role": role, "content": text} if text.strip() else None

        text_messages: list[dict] = []
        seen = {0}  # 首条必取
        t = _msg_text(parent_messages[0])
        if t:
            text_messages.append(t)
        tail_start = max(1, len(parent_messages) - 5)
        for i in range(tail_start, len(parent_messages)):
            if i not in seen:
                t = _msg_text(parent_messages[i])
                if t:
                    text_messages.append(t)
        return text_messages

    def _build_skill_info(self, skill_names: list[str]) -> str:
        """构建技能信息文本，包含技能完整说明。"""
        skill_info_lines = (
            [f"将使用技能: {', '.join(skill_names)}"]
            if skill_names
            else ["无指定技能"]
        )

        if skill_names:
            from ..skills.loader import _registry as _gen_skill_registry
            skill_bodies = []
            for name in skill_names:
                sk = _gen_skill_registry.get(name)
                if sk:
                    body_text = sk.body
                    if len(body_text) > self.skill_body_max_chars:
                        body_text = (
                            body_text[:self.skill_body_max_chars]
                            + "\n...[技能说明已截断，完整内容可通过 Skill 工具加载]"
                        )
                    skill_bodies.append(f"### {name}\n\n{body_text}")
            if skill_bodies:
                skill_info_lines.append("## 技能完整说明\n")
                skill_info_lines.append("\n---\n".join(skill_bodies))

        return "\n".join(skill_info_lines)
