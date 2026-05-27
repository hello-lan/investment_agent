"""运行时上下文裁剪策略 — 在 Agent 执行循环中每 N 步裁剪旧消息。

与运行前的 ContextManager（预算规划/摘要/缓存）不同，
RuntimeTrimmer 在引擎循环运行时逐步释放上下文空间。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .token_utils import truncate_text
from .trim_limits import resolve_limit


class RuntimeTrimmer(ABC):
    """运行时上下文裁剪策略的抽象基类。"""

    @abstractmethod
    def trim(self, messages: list[dict], current_step: int) -> list[dict]:
        """裁剪消息列表，返回裁剪后的列表。"""
        ...


class DefaultRuntimeTrimmer(RuntimeTrimmer):
    """默认运行时裁剪策略：保留最近 N 轮对话，旧消息剥离 reasoning 并截断 tool_result。

    "一轮" = 一条 assistant 消息 + 其后的一条 user(tool_result) 消息。
    messages[0]（原始用户问题）始终完整保留。
    """

    def __init__(self, tool_trim_limits: dict | None = None, keep_recent: int = 5):
        self._tool_trim_limits = tool_trim_limits or {}
        self._keep_recent = keep_recent

    def trim(self, messages: list[dict], current_step: int) -> list[dict]:
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
                        tool_name = self._guess_tool_name(block, messages, i)
                        raw = str(block.get("content", ""))
                        limit = resolve_limit(tool_name, self._tool_trim_limits)
                        b["content"] = self._truncate_text(raw, limit)
                    new_blocks.append(b)
                trimmed.append({"role": "user", "content": new_blocks})

            else:
                trimmed.append(msg)

        return trimmed

    @staticmethod
    def _guess_tool_name(block: dict, messages: list[dict], msg_idx: int) -> str | None:
        """通过 tool_use_id 反查工具名称。"""
        tool_id = block.get("tool_use_id", "")
        if not tool_id:
            return None
        for i in range(msg_idx - 1, -1, -1):
            m = messages[i]
            if m.get("role") != "assistant":
                continue
            content = m.get("content", [])
            if not isinstance(content, list):
                continue
            for b in content:
                if b.get("type") == "tool_use" and b.get("id") == tool_id:
                    return b.get("name")
        return None

    @staticmethod
    def _truncate_text(text: str, max_chars: int) -> str:
        return truncate_text(text, max_chars, mode="chars", marker="...[已截断]")


class NoOpRuntimeTrimmer(RuntimeTrimmer):
    """不做任何裁剪，消息列表原样返回。"""

    def trim(self, messages: list[dict], current_step: int) -> list[dict]:
        return messages


def get_runtime_trimmer(strategy: str, tool_trim_limits: dict | None = None) -> RuntimeTrimmer:
    """根据策略名创建 RuntimeTrimmer 实例。

    Args:
        strategy: "default" | "none"
        tool_trim_limits: 工具结果截断限制（仅 default 策略使用）
    """
    if strategy == "none":
        return NoOpRuntimeTrimmer()
    return DefaultRuntimeTrimmer(tool_trim_limits=tool_trim_limits)
