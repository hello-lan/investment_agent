"""上下文裁剪器 — 从 AgentEngine 提取。

管理执行循环中的周期性上下文压缩。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..context.runtime_compressor import RuntimeCompressor


class ContextTrimmer:
    """每 N 步裁剪旧消息，保留系统消息和最近轮次。"""

    def __init__(
        self,
        compressor: "RuntimeCompressor | None" = None,
        interval: int = 0,
    ):
        self._compressor = compressor
        self._interval = interval

    async def maybe_trim(
        self, messages: list[dict], step: int,
    ) -> tuple[list[dict], dict | None]:
        """根据需要裁剪上下文。

        Returns:
            (possibly_trimmed_messages, trim_event_or_none)
        """
        if (
            self._compressor is not None
            and self._interval > 0
            and step > 1
            and step % self._interval == 0
        ):
            # 检查是否 NoOp
            from ..context.runtime_compressor import NoOpRuntimeCompressor
            if not isinstance(self._compressor, NoOpRuntimeCompressor):
                messages = await self._compressor.compress(messages, step)
                return messages, {"type": "context_trim", "step": step}
        return messages, None
