"""上下文裁剪器 — 从 AgentEngine 提取。

管理执行循环中的周期性上下文压缩，支持两种触发模式：
1. 间隔触发（context_trim_interval）—— 每 N 步压缩一次
2. Token 阈值触发（token_threshold）—— 累计 input_tokens 超限时安全压缩
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context.runtime_compressor import RuntimeCompressor


class ContextTrimmer:
    """上下文裁剪器，支持间隔 + token 阈值双模式触发。

    间隔模式：每 N 步压缩旧消息（适合主动预算管理）。
    Token 阈值模式：仅在累计消耗超过阈值时介入（安全阀，默认优先使用）。
    """

    def __init__(
        self,
        compressor: "RuntimeCompressor | None" = None,
        interval: int = 0,
        token_threshold: int = 0,
    ):
        self._compressor = compressor
        self._interval = interval
        self._token_threshold = token_threshold

    async def maybe_trim(
        self, messages: list[dict], step: int, total_input_tokens: int = 0,
    ) -> tuple[list[dict], dict | None]:
        """根据需要裁剪上下文。

        触发条件（任一满足即触发）：
        - 间隔模式：step > 1 且 step % interval == 0
        - 阈值模式：total_input_tokens > token_threshold > 0

        Returns:
            (possibly_trimmed_messages, trim_event_or_none)
        """
        should_trim = False
        trigger_reason = ""

        # 间隔触发
        if (
            self._interval > 0
            and step > 1
            and step % self._interval == 0
        ):
            should_trim = True
            trigger_reason = f"interval({self._interval})"

        # Token 阈值触发（安全阀 — 即使间隔关闭也会触发）
        if (
            not should_trim
            and self._token_threshold > 0
            and total_input_tokens > self._token_threshold
        ):
            should_trim = True
            trigger_reason = f"token_threshold({self._token_threshold})"

        if not should_trim:
            return messages, None

        from ..context.runtime_compressor import NoOpRuntimeCompressor
        if self._compressor is None or isinstance(self._compressor, NoOpRuntimeCompressor):
            return messages, None

        messages = await self._compressor.compress(messages, step)
        return messages, {
            "type": "context_trim",
            "step": step,
            "trigger": trigger_reason,
        }
