"""上下文裁剪器 — 从 AgentEngine 提取。

基于 Token 阈值触发安全压缩：累计 input_tokens 超限时自动压缩旧消息。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context.runtime_compressor import RuntimeCompressor


class ContextTrimmer:
    """上下文裁剪器，基于 Token 阈值触发压缩。

    仅当单次 LLM 调用的累计 input_tokens 超过阈值时介入（安全阀）。
    不做周期性主动压缩，以保留完整对话历史确保前缀缓存命中。
    """

    def __init__(
        self,
        compressor: "RuntimeCompressor | None" = None,
        token_threshold: int = 0,
    ):
        self._compressor = compressor
        self._token_threshold = token_threshold

    async def maybe_trim(
        self, messages: list[dict], step: int, total_input_tokens: int = 0,
    ) -> tuple[list[dict], dict | None]:
        """根据需要裁剪上下文。

        触发条件：total_input_tokens > token_threshold > 0

        Returns:
            (possibly_trimmed_messages, trim_event_or_none)
        """
        if not (
            self._token_threshold > 0
            and total_input_tokens > self._token_threshold
        ):
            return messages, None

        from ..context.runtime_compressor import NoOpRuntimeCompressor
        if self._compressor is None or isinstance(self._compressor, NoOpRuntimeCompressor):
            return messages, None

        messages = await self._compressor.compress(messages, step)
        return messages, {
            "type": "context_trim",
            "step": step,
            "trigger": f"token_threshold({self._token_threshold})",
        }
