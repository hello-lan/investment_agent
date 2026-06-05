"""Prompt Cache 标记策略 — 从通用组件中解耦 Anthropic 特定缓存逻辑。

通过 CacheStrategy 抽象，ContextManager 和 SlowThinkStrategy 无需
感知具体的缓存标记格式（Anthropic ephemeral 等）。
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class CacheStrategy(ABC):
    """Provider 特定的 prompt cache 标记注入策略。"""

    @abstractmethod
    def apply_to_system(self, system_prompt: str | list[dict]) -> list[dict]:
        """对 system prompt 添加缓存标记。"""
        ...

    @abstractmethod
    def apply_to_first_message(self, msg: dict) -> dict:
        """对首条消息添加缓存标记（用于慢思考等场景）。"""
        ...

    @abstractmethod
    def apply_to_tools(self, tools: list[dict]) -> list[dict]:
        """对工具列表添加缓存标记。"""
        ...

    @abstractmethod
    def apply_to_messages(
        self, system_prompt: str, messages: list[dict],
    ) -> tuple[list[dict], list[dict], bool]:
        """对 system + messages 添加结构化缓存标记。

        Returns:
            (system_blocks, cached_messages, applied) — system_blocks 是
            带 cache_control 的 content block 列表。
        """
        ...


class AnthropicCacheStrategy(CacheStrategy):
    """Anthropic ephemeral cache_control 标记策略。

    缓存结构: [system (cached)] [summary (cached)] [msg_1] ... [msg_N]
    """

    def apply_to_system(self, system_prompt: str | list[dict]) -> list[dict]:
        """str → 转为带 cache_control 的 content block 列表；list[dict] → 原样返回。"""
        if isinstance(system_prompt, str) and system_prompt:
            return [
                {
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        return system_prompt if isinstance(system_prompt, list) else [system_prompt]

    def apply_to_first_message(self, msg: dict) -> dict:
        """给首条消息的内容添加 ephemeral 缓存标记。"""
        content = msg.get("content", "")
        if isinstance(content, str):
            return {
                "role": msg["role"],
                "content": [
                    {
                        "type": "text",
                        "text": content,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        if isinstance(content, list) and content:
            content[0] = {**content[0], "cache_control": {"type": "ephemeral"}}
        return msg

    def apply_to_tools(self, tools: list[dict]) -> list[dict]:
        """给最后一个 tool 添加 ephemeral 缓存标记。"""
        tools = list(tools)
        if tools and "cache_control" not in tools[-1]:
            tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}
        return tools

    def apply_to_messages(
        self, system_prompt: str, messages: list[dict],
    ) -> tuple[list[dict], list[dict], bool]:
        """给 system + 首条消息添加 cache 标记。"""
        system_blocks = [
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        cached_messages = list(messages)
        if cached_messages:
            first = cached_messages[0]
            content = first.get("content", "")
            if isinstance(content, list):
                new_content = []
                for i, block in enumerate(content):
                    b = dict(block)
                    if i == 0 and b.get("type") == "text":
                        b["cache_control"] = {"type": "ephemeral"}
                    new_content.append(b)
                cached_messages[0] = {"role": first["role"], "content": new_content}
            elif isinstance(content, str):
                cached_messages[0] = {
                    "role": first["role"],
                    "content": [
                        {
                            "type": "text",
                            "text": content,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                }

        return system_blocks, cached_messages, True


class NoOpCacheStrategy(CacheStrategy):
    """无缓存策略 — 用于 OpenAI 兼容 Provider。"""

    def apply_to_system(self, system_prompt):
        return system_prompt if isinstance(system_prompt, (str, list)) else str(system_prompt)

    def apply_to_first_message(self, msg: dict) -> dict:
        return msg

    def apply_to_tools(self, tools: list[dict]) -> list[dict]:
        return list(tools)

    def apply_to_messages(
        self, system_prompt: str, messages: list[dict],
    ) -> tuple[str, list[dict], bool]:
        return system_prompt, messages, False


def get_cache_strategy(provider_type: str) -> CacheStrategy:
    """工厂函数：根据 provider_type 返回对应的缓存策略。

    Args:
        provider_type: "anthropic" | "openai" 等
    """
    from ..constants import ProviderType
    if provider_type == ProviderType.ANTHROPIC:
        return AnthropicCacheStrategy()
    return NoOpCacheStrategy()
