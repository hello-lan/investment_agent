"""LLM Provider 抽象层：共享数据类型 + 多模型适配器。

数据类型（ToolCall, LLMResponse）定义在 types.py，供 engine / tool_executor 等模块共用。
ModelProvider ABC 定义统一接口，ClaudeProvider 和 OpenAICompatProvider
分别对接 Anthropic SDK 和 OpenAI Chat Completions 格式。
"""

import logging
from abc import ABC, abstractmethod
from typing import Any

from ..constants import ProviderType, StopReason
from .message_converter import AnthropicToOpenAIMessageConverter, AnthropicToOpenAIToolConverter
from .response_parser import OpenAIResponseParser
from .types import LLMResponse, ToolCall

_log = logging.getLogger(__name__)


# ── Provider 基类 ───────────────────────────────────────────────────────────

class ModelProvider(ABC):
    """多模型抽象层基类：ClaudeProvider / OpenAICompatProvider 继承此接口"""

    # 定价信息（由 app 层工厂方法设置）
    input_price: float | None = None
    output_price: float | None = None
    currency: str = "USD"

    def convert_messages(self, messages: list[dict]) -> list[dict]:
        """格式转换：Anthropic 原生格式无需转换，OpenAI 需要转换。

        公开 API，供 engine 等外部组件调用。
        """
        return messages

    # 保留 protected 别名，向后兼容
    _convert_messages = convert_messages

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        system: str = "",
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse: ...


# ── Anthropic Claude ────────────────────────────────────────────────────────

class ClaudeProvider(ModelProvider):
    provider_type = ProviderType.ANTHROPIC

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        import anthropic
        self.client = anthropic.AsyncAnthropic(api_key=api_key or None)
        self.model = model

    async def chat(self, messages, system="", tools=None, max_tokens=4096, temperature=0.7) -> LLMResponse:
        # Anthropic ephemeral 缓存标记：确保 system 和 tools 被正确标记
        system = self._ensure_cache_markers(system)
        if tools:
            tools = self._ensure_tools_cache(tools)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = tools
        if temperature is not None:
            kwargs["temperature"] = temperature

        resp = await self.client.messages.create(**kwargs)

        # 解析 Anthropic content blocks
        content = ""
        tool_calls = []
        for block in resp.content:
            if block.type == "text":
                content = block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input))

        # 提取缓存命中指标
        usage = resp.usage
        cache_read = getattr(usage, 'cache_read_input_tokens', 0) or 0
        cache_creation = getattr(usage, 'cache_creation_input_tokens', 0) or 0

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            stop_reason=resp.stop_reason or StopReason.END_TURN,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_creation,
        )

    @staticmethod
    def _ensure_cache_markers(system) -> Any:
        """确保 system prompt 有 ephemeral 缓存标记。

        - str → 转为带 cache_control 的 content block 列表
        - list[dict] → 原样返回（ContextManager 已处理）
        """
        if isinstance(system, str) and system:
            return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        return system

    @staticmethod
    def _ensure_tools_cache(tools: list[dict]) -> list[dict]:
        """确保最后一个 tool 有 ephemeral 缓存标记。"""
        tools = list(tools)
        if tools and "cache_control" not in tools[-1]:
            tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}
        return tools


# ── OpenAI 兼容接口（DeepSeek / Qwen / Ollama / vLLM 等）────────────────

class OpenAICompatProvider(ModelProvider):
    provider_type = ProviderType.OPENAI

    def __init__(self, api_key: str, model: str, base_url: str = "https://api.openai.com/v1"):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=api_key or None, base_url=base_url)
        self.model = model

    def convert_messages(self, messages: list[dict]) -> list[dict]:
        """将 Anthropic 格式的消息列表转换为 OpenAI Chat Completions 格式。"""
        return AnthropicToOpenAIMessageConverter.convert(messages)

    async def chat(self, messages, system="", tools=None, max_tokens=4096, temperature=0.7) -> LLMResponse:
        all_messages = []
        if system:
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": all_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = AnthropicToOpenAIToolConverter.convert(tools)

        resp = await self.client.chat.completions.create(**kwargs)
        return OpenAIResponseParser.parse(resp, self.model)
