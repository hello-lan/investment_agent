"""LLM Provider 抽象层：共享数据类型 + 多模型适配器。

数据类型（ToolCall, LLMResponse）供 engine / tool_executor 等模块共用。
ModelProvider ABC 定义统一接口，ClaudeProvider 和 OpenAICompatProvider
分别对接 Anthropic SDK 和 OpenAI Chat Completions 格式。
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)


# ── 数据结构 ────────────────────────────────────────────────────────────────

@dataclass
class ToolCall:
    """LLM 返回的单个工具调用"""
    id: str
    name: str
    input: dict


@dataclass
class LLMResponse:
    """统一的 LLM 响应格式，屏蔽不同 Provider 的差异"""
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    extra_blocks: list[dict] = field(default_factory=list)  # Anthropic 专有 content blocks
    reasoning_content: str | None = None  # 深度求索等模型的思考内容
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = "end_turn"
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0


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
    provider_type = "anthropic"

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
            stop_reason=resp.stop_reason or "end_turn",
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
    provider_type = "openai"

    def __init__(self, api_key: str, model: str, base_url: str = "https://api.openai.com/v1"):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=api_key or None, base_url=base_url)
        self.model = model

    def convert_messages(self, messages: list[dict]) -> list[dict]:
        """将 Anthropic 格式的消息列表转换为 OpenAI Chat Completions 格式

        Anthropic 的 content 是 list[content_block]，OpenAI 则是 string 或 tool_calls，
        这里需要把 tool_use / tool_result 等 block 转换成 OpenAI 的 tool_calls / tool 角色。
        """
        import json
        converted = []
        for msg in messages:
            content = msg.get("content")
            role = msg.get("role", "")
            if role == "assistant" and isinstance(content, list):
                text_parts = []
                tool_calls = []
                reasoning = None
                for block in content:
                    t = block.get("type", "")
                    if t == "text":
                        text_parts.append(block["text"])
                    elif t == "reasoning":
                        reasoning = block.get("content")
                    elif t == "tool_use":
                        tool_calls.append({
                            "id": block["id"],
                            "type": "function",
                            "function": {
                                "name": block["name"],
                                "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                            },
                        })
                entry: dict[str, Any] = {"role": "assistant", "content": "\n".join(text_parts) or None}
                if reasoning:
                    entry["reasoning_content"] = reasoning
                if tool_calls:
                    entry["tool_calls"] = tool_calls
                converted.append(entry)
            elif role == "user" and isinstance(content, list):
                # user 消息中的 tool_result block → OpenAI tool 角色
                for block in content:
                    t = block.get("type", "")
                    if t == "tool_result":
                        c = block.get("content", "")
                        if isinstance(c, list):
                            c = "\n".join(b.get("text", "") for b in c if b.get("type") == "text")
                        converted.append({"role": "tool", "tool_call_id": block["tool_use_id"], "content": str(c)})
                    elif t == "text":
                        converted.append({"role": "user", "content": block["text"]})
            else:
                converted.append(msg)
        return converted

    async def chat(self, messages, system="", tools=None, max_tokens=4096, temperature=0.7) -> LLMResponse:
        import json
        all_messages = []
        if system:
            # OpenAI 用 system role，不是 system 参数
            all_messages.append({"role": "system", "content": system})
        all_messages.extend(messages)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": all_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            # 将 Anthropic 格式的 tool schema 转成 OpenAI function 格式
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get("input_schema", {}),
                    },
                }
                for t in tools
            ]

        resp = await self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message

        content = msg.content or ""
        reasoning = getattr(msg, "reasoning_content", None) or None
        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    _log.warning(
                        "Skipping malformed tool call arguments from model %s: %s",
                        self.model, tc.function.arguments[:200]
                    )
                    continue
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    input=args,
                ))

        # 映射 OpenAI finish_reason → 统一 stop_reason
        raw_reason = (resp.choices[0].finish_reason or "end_turn")
        if raw_reason == "stop":
            stop_reason = "end_turn"
        elif raw_reason == "tool_calls":
            stop_reason = "tool_use"
        elif raw_reason == "length":
            # max_tokens 耗尽：输出被截断，tool_calls 可能不完整 → 丢弃
            if tool_calls:
                _log.warning(
                    "Response truncated (finish_reason=length), discarding %d tool calls",
                    len(tool_calls),
                )
                tool_calls.clear()
            stop_reason = "length"
        else:
            stop_reason = raw_reason

        # 提取缓存指标（DeepSeek 自动前缀缓存 / OpenAI prompt caching）
        cache_read = 0
        cache_creation = 0
        if resp.usage:
            # DeepSeek 格式
            cache_read = getattr(resp.usage, 'prompt_cache_hit_tokens', 0) or 0
            cache_creation = getattr(resp.usage, 'prompt_cache_miss_tokens', 0) or 0
            # OpenAI 格式
            if not cache_read:
                details = getattr(resp.usage, 'prompt_tokens_details', None)
                if details:
                    cache_read = getattr(details, 'cached_tokens', 0) or 0

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            reasoning_content=reasoning,
            input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            output_tokens=resp.usage.completion_tokens if resp.usage else 0,
            stop_reason=stop_reason,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_creation,
        )
