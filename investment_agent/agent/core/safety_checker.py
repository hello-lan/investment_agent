"""执行安全检查器 — 从 AgentEngine 提取。

封装中断检查、token 预算检查、步数预算预警，返回终止事件或注入警告。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

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
            if isinstance(last_content, str) and "步数预算警告" in last_content:
                return True  # 已注入过

            warning = (
                f"[步数预算警告] 剩余步数: {remaining}/{engine.max_steps}。"
                f"请评估当前进度：如果仍在数据准备阶段，考虑跳过中间步骤，"
                f"直接使用已有数据快速进入核心分析。优先委派而非亲自调试。"
            )
            messages.append({"role": "user", "content": warning})
            return True
        return False
