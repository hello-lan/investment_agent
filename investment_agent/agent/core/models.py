from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


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


# ── Provider 基类 ───────────────────────────────────────────────────────────

class ModelProvider(ABC):
    """多模型抽象层基类：ClaudeProvider / OpenAICompatProvider 继承此接口"""

    def _convert_messages(self, messages: list[dict]) -> list[dict]:
        """格式转换钩子：Anthropic 原生格式无需转换，OpenAI 需要转换"""
        return messages

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
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        import anthropic
        self.client = anthropic.AsyncAnthropic(api_key=api_key or None)
        self.model = model

    async def chat(self, messages, system="", tools=None, max_tokens=4096, temperature=0.7) -> LLMResponse:
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

        # 解析 Anthropic content blocks：text 或 tool_use
        content = ""
        tool_calls = []
        for block in resp.content:
            if block.type == "text":
                content = block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input))

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            stop_reason=resp.stop_reason or "end_turn",
        )


# ── OpenAI 兼容接口（DeepSeek / Qwen / Ollama / vLLM 等）────────────────

class OpenAICompatProvider(ModelProvider):
    def __init__(self, api_key: str, model: str, base_url: str = "https://api.openai.com/v1"):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=api_key or None, base_url=base_url)
        self.model = model

    def _convert_messages(self, messages: list[dict]) -> list[dict]:
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
                tool_calls.append(ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    input=json.loads(tc.function.arguments),
                ))

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            reasoning_content=reasoning,
            input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            output_tokens=resp.usage.completion_tokens if resp.usage else 0,
            stop_reason="tool_use" if tool_calls else "end_turn",
        )


# ── 工厂函数 ────────────────────────────────────────────────────────────────

async def get_provider(model_id: str | None = None) -> ModelProvider:
    """从数据库 models 表读取配置，创建对应的 ModelProvider 实例"""
    from ...app.db import get_db
    async with get_db() as db:
        if model_id:
            row = await db.execute("SELECT * FROM models WHERE id = ?", (model_id,))
        else:
            row = await db.execute("SELECT * FROM models WHERE is_default = 1 LIMIT 1")
        cfg = await row.fetchone()

        if not cfg:
            # 降级：取数据库中第一个模型
            row = await db.execute("SELECT * FROM models LIMIT 1")
            cfg = await row.fetchone()

    if not cfg:
        raise ValueError("No model configured. Please add a model in Settings.")

    if cfg["type"] == "anthropic":
        return ClaudeProvider(api_key=cfg["api_key"], model=cfg["model"])
    else:
        return OpenAICompatProvider(
            api_key=cfg["api_key"],
            model=cfg["model"],
            base_url=cfg["base_url"] or "https://api.openai.com/v1",
        )
