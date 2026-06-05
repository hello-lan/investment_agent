"""慢思考策略 — 从 AgentEngine 提取的自适应反思触发与执行逻辑。

在 Agent 执行循环中根据信号决定何时触发慢思考，并执行反思 LLM 调用。
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator, TYPE_CHECKING

from ..config import SLOW_THINK_PROMPT

if TYPE_CHECKING:
    from .provider import ModelProvider

_log = logging.getLogger(__name__)


class SlowThinkStrategy:
    """自适应慢思考：基于运行时信号触发，而非固定间隔。

    触发条件（优先级从高到低）：
    0. 步数预算不足（≤25% 剩余）→ 强制策略调整
    1. 工具连续失败 ≥2 次 → 需要重新规划
    2. 最近 5 步频繁切换工具（≥3 种不同工具）→ 策略不稳定
    3. 距上次反思超过 MAX_INTERVAL 步 → 保底触发
    """

    MAX_INTERVAL = 8

    def __init__(self):
        self._consecutive_failures = 0
        self._tool_switches = 0
        self._last_tool: str | None = None
        self._last_slow_think_step = 0

    # ── 状态记录 ────────────────────────────────────────────────────────

    def record_tool_result(self, has_error: bool, tool_names: list[str]) -> None:
        """工具执行后调用，更新内部状态。

        Args:
            has_error: 工具结果是否包含错误
            tool_names: 本次调用的工具名列表
        """
        # 追踪失败
        if has_error:
            self._consecutive_failures += 1
        else:
            self._consecutive_failures = 0

        # 追踪工具切换
        for name in tool_names:
            if name != self._last_tool:
                if self._last_tool is not None:
                    self._tool_switches += 1
                self._last_tool = name

    def reset_switches(self) -> None:
        """反思后重置切换计数。"""
        self._tool_switches = 0

    # ── 触发判断 ────────────────────────────────────────────────────────

    def should_think(
        self, step: int, max_steps: int, slow_think_interval: int,
    ) -> str | None:
        """判断是否应触发慢思考。

        Returns:
            触发原因字符串，None 表示不触发。
        """
        trigger = ""

        # 条件 0: 步数预算不足
        remaining = max_steps - step
        step_warn_threshold = max(3, int(max_steps * 0.25))
        if remaining <= step_warn_threshold:
            trigger = f"步数预算不足（剩余 {remaining}/{max_steps}），需要调整策略"

        # 条件 1: 连续失败
        if not trigger and self._consecutive_failures >= 2:
            trigger = "工具连续失败，需要重新规划"

        # 条件 2: 频繁切换工具
        if not trigger and self._tool_switches >= 3:
            trigger = "策略不稳定，频繁切换工具"

        # 条件 3: 保底触发
        steps_since = step - self._last_slow_think_step
        if not trigger and steps_since >= self.MAX_INTERVAL:
            trigger = f"距上次反思已 {steps_since} 步"

        # 传统 fixed-interval 兼容
        if not trigger and slow_think_interval > 0 and step > 1:
            if step % slow_think_interval == 0:
                trigger = f"定时反思 @ step {step}"

        return trigger or None

    # ── 反思执行 ─────────────────────────────────────────────────────────

    async def think(
        self,
        messages: list[dict],
        step: int,
        provider: "ModelProvider",
        extract_role_fn,
        temperature: float | None = None,
        max_tokens: int | None = None,
        slow_think_max_tokens: int = 512,
        total_input_tokens: int = 0,
        total_output_tokens: int = 0,
        total_cache_read_tokens: int = 0,
        total_cache_creation_tokens: int = 0,
    ) -> tuple[str | None, int, int, int, int]:
        """执行慢思考 LLM 调用。

        Returns:
            (reflection_text | None, new_total_input, new_total_output,
             new_cache_read, new_cache_creation)
        """
        self._last_slow_think_step = step
        self._tool_switches = 0  # 反思后重置

        slim_messages = [self._ensure_cache_on_first_message(messages[0])]
        assistant_positions = [
            i for i, m in enumerate(messages) if m.get("role") == "assistant"
        ]
        keep_from = (
            assistant_positions[-5] if len(assistant_positions) >= 5
            else (assistant_positions[0] if assistant_positions else 0)
        )
        slim_messages.extend(messages[keep_from:])

        prompt = SLOW_THINK_PROMPT.format(step=step)
        slim_messages.append({"role": "user", "content": prompt})

        minimal_system = extract_role_fn()

        try:
            think_kwargs: dict = {
                "messages": provider.convert_messages(slim_messages),
                "system": minimal_system,
            }
            if temperature is not None:
                think_kwargs["temperature"] = temperature
            if max_tokens is not None:
                think_kwargs["max_tokens"] = min(max_tokens, slow_think_max_tokens)
            else:
                think_kwargs["max_tokens"] = slow_think_max_tokens
            resp = await provider.chat(**think_kwargs)
            new_input = total_input_tokens + resp.input_tokens
            new_output = total_output_tokens + resp.output_tokens
            new_cache_read = total_cache_read_tokens + resp.cache_read_tokens
            new_cache_creation = total_cache_creation_tokens + resp.cache_creation_tokens
            if resp.content:
                return (
                    resp.content.strip(),
                    new_input, new_output, new_cache_read, new_cache_creation,
                )
        except Exception:
            _log.warning("Slow think failed at step %d", step, exc_info=True)

        return None, total_input_tokens, total_output_tokens, total_cache_read_tokens, total_cache_creation_tokens

    @staticmethod
    def _ensure_cache_on_first_message(msg: dict) -> dict:
        """给消息添加 cache_control 标记（Anthropic 格式）。"""
        content = msg.get("content", "")
        if isinstance(content, str):
            return {
                "role": msg["role"],
                "content": [
                    {"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}
                ],
            }
        if isinstance(content, list) and content:
            content[0] = {**content[0], "cache_control": {"type": "ephemeral"}}
        return msg
