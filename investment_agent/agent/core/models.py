from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = "end_turn"


class ModelProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        system: str = "",
        tools: list[dict] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse: ...


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

        resp = await self.client.messages.create(**kwargs)

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


class OpenAICompatProvider(ModelProvider):
    def __init__(self, api_key: str, model: str, base_url: str = "https://api.openai.com/v1"):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=api_key or None, base_url=base_url)
        self.model = model

    async def chat(self, messages, system="", tools=None, max_tokens=4096, temperature=0.7) -> LLMResponse:
        import json
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
            input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            output_tokens=resp.usage.completion_tokens if resp.usage else 0,
            stop_reason="tool_use" if tool_calls else "end_turn",
        )


async def get_provider(model_id: str | None = None) -> ModelProvider:
    from ...app.db import get_db
    async with get_db() as db:
        if model_id:
            row = await db.execute("SELECT * FROM models WHERE id = ?", (model_id,))
        else:
            row = await db.execute("SELECT * FROM models WHERE is_default = 1 LIMIT 1")
        cfg = await row.fetchone()

        if not cfg:
            # fallback: first model in table
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
