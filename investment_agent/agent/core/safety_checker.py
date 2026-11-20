"""执行安全检查器 — 从 AgentEngine 提取。

封装中断检查、token 预算检查、步数预算预警，返回终止事件或注入警告。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..prompts import STEP_BUDGET_MARKER, STEP_BUDGET_WARNING

if TYPE_CHECKING:
    from .engine import AgentEngine


@dataclass
class SafetyCheckResult:
    """安全检查结果。"""
    stop_event: dict | None = None      # 非 None → 终止执行
    budget_warning_injected: bool = False  # 是否已向 messages 注入步数警告


class SafetyChecker:
    """执行循环安全检查：中断、token 预算、步数预算。"""

    def check(
        self, engine: "AgentEngine", step: int, messages: list[dict],
    ) -> SafetyCheckResult:
        """执行全部安全检查。

        Returns:
            SafetyCheckResult — 包含终止事件或预算警告标志。
        """
        # 用户中断
        if engine._interrupt.is_set():
            return SafetyCheckResult(
                stop_event={"type": "interrupted", "step": step}
            )

        # Token 预算耗尽
        used = engine.total_input_tokens + engine.total_output_tokens
        if used >= engine.token_budget:
            return SafetyCheckResult(
                stop_event={
                    "type": "error",
                    "message": f"Token budget ({engine.token_budget}) exceeded.",
                }
            )

        # 步数预算预警
        warning_injected = self._check_step_budget(engine, step, messages)

        return SafetyCheckResult(budget_warning_injected=warning_injected)

    @staticmethod
    def _check_step_budget(
        engine: "AgentEngine", step: int, messages: list[dict],
    ) -> bool:
        """步数预算预警：剩余步数不足时注入提醒。返回 True 表示已注入。"""
        remaining = engine.max_steps - step
        warn_threshold = max(5, int(engine.max_steps * 0.25))
        if remaining <= warn_threshold:
            last_msg = messages[-1] if messages else {}
            last_content = last_msg.get("content", "")
            if isinstance(last_content, str) and STEP_BUDGET_MARKER in last_content:
                return True  # 已注入过

            warning = STEP_BUDGET_WARNING.format(
                remaining=remaining,
                max_steps=engine.max_steps,
            )
            messages.append({"role": "user", "content": warning})
            return True
        return False
