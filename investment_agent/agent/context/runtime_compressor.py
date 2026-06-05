"""运行时上下文压缩策略 — 在 Agent 执行循环中每 N 步压缩旧消息。

与运行前的 ContextManager（预算规划/摘要/缓存）不同，
RuntimeCompressor 在引擎循环运行时逐步释放上下文空间。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from .token_utils import truncate_text

from ..constants import RuntimeTrimStrategy

if TYPE_CHECKING:
    from .context_offloader import ContextOffloader


class RuntimeCompressor(ABC):
    """运行时上下文压缩策略的抽象基类。"""

    @abstractmethod
    async def compress(self, messages: list[dict], current_step: int) -> list[dict]:
        """压缩消息列表，返回压缩后的列表。"""
        ...


class CompressRuntimeCompressor(RuntimeCompressor):
    """压缩运行时上下文策略：保留最近 N 轮对话，旧消息剥离 reasoning 并卸载大 tool_result。

    "一轮" = 一条 assistant 消息 + 其后的一条 user(tool_result) 消息。
    messages[0]（原始用户问题）始终完整保留。

    tool_result 处理：
    - 有 offloader 且内容超阈值 → 卸载到文件，替换为摘要+路径占位符
    - 否则 → 原样保留（不再截断）
    """

    def __init__(
        self,
        tool_trim_limits: dict | None = None,
        keep_recent: int = 5,
        offloader: "ContextOffloader | None" = None,
    ):
        self._tool_trim_limits = tool_trim_limits or {}
        self._keep_recent = keep_recent
        self._offloader = offloader

    async def compress(self, messages: list[dict], current_step: int) -> list[dict]:
        if len(messages) <= 1:
            return messages

        assistant_indices = [
            i for i, m in enumerate(messages) if m.get("role") == "assistant"
        ]
        if len(assistant_indices) <= self._keep_recent:
            return messages

        retain_from = assistant_indices[-(self._keep_recent)]

        trimmed = []
        for i, msg in enumerate(messages):
            if i == 0 or i >= retain_from:
                trimmed.append(msg)
                continue

            role = msg.get("role", "")
            content = msg.get("content", "")

            if role == "assistant" and isinstance(content, list):
                new_blocks = []
                for block in content:
                    if block.get("type") == "reasoning":
                        new_blocks.append(
                            {"type": "reasoning", "content": "[推理过程已压缩]"}
                        )
                    else:
                        new_blocks.append(block)
                trimmed.append({"role": "assistant", "content": new_blocks})

            elif role == "user" and isinstance(content, list):
                new_blocks = []
                for block in content:
                    b = dict(block)
                    if block.get("type") == "tool_result":
                        raw = str(block.get("content", ""))
                        if self._offloader and self._offloader.should_offload(raw):
                            b["content"] = await self._offloader.offload(raw)
                        # 小内容原样保留，不再截断
                    new_blocks.append(b)
                trimmed.append({"role": "user", "content": new_blocks})

            else:
                trimmed.append(msg)

        return trimmed

    @staticmethod
    def _truncate_text(text: str, max_chars: int) -> str:
        return truncate_text(text, max_chars, mode="chars", marker="...[已截断]")


class NoOpRuntimeCompressor(RuntimeCompressor):
    """不做任何压缩，消息列表原样返回。"""

    async def compress(self, messages: list[dict], current_step: int) -> list[dict]:
        return messages


def get_runtime_compressor(
    strategy: str,
    tool_trim_limits: dict | None = None,
    offloader: "ContextOffloader | None" = None,
) -> RuntimeCompressor:
    """根据策略名创建 RuntimeCompressor 实例。

    Args:
        strategy: "compress" | "off"
        tool_trim_limits: 工具结果截断限制（保留兼容，当前未使用）
        offloader: 上下文卸载器（仅 compress 策略使用）
    """
    if strategy == RuntimeTrimStrategy.OFF:
        return NoOpRuntimeCompressor()
    return CompressRuntimeCompressor(
        tool_trim_limits=tool_trim_limits,
        offloader=offloader,
    )
