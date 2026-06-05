"""Anthropic ↔ OpenAI 格式转换器。

将 Anthropic content-block 格式转换为 OpenAI Chat Completions 格式，
从 OpenAICompatProvider 中提取为独立的无状态转换器，便于测试和复用。
"""

from __future__ import annotations

import json


class AnthropicToOpenAIMessageConverter:
    """将 Anthropic content-block 消息列表转换为 OpenAI Chat Completions 格式。

    Anthropic 的 content 是 list[content_block]（含 tool_use / tool_result 等），
    OpenAI 则是 string 或 tool_calls / tool 角色。
    """

    @staticmethod
    def convert(messages: list[dict]) -> list[dict]:
        converted = []
        for msg in messages:
            content = msg.get("content")
            role = msg.get("role", "")
            if role == "assistant" and isinstance(content, list):
                entry = AnthropicToOpenAIMessageConverter._convert_assistant(content)
                converted.append(entry)
            elif role == "user" and isinstance(content, list):
                converted.extend(
                    AnthropicToOpenAIMessageConverter._convert_user(content)
                )
            else:
                converted.append(msg)
        return converted

    @staticmethod
    def _convert_assistant(content: list) -> dict:
        """转换 assistant 消息的 content blocks → OpenAI 格式。

        text/ reasoning → content/reasoning_content 字段
        tool_use → tool_calls 数组
        """
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
                        "arguments": json.dumps(
                            block.get("input", {}), ensure_ascii=False
                        ),
                    },
                })
        entry: dict = {"role": "assistant", "content": "\n".join(text_parts) or None}
        if reasoning:
            entry["reasoning_content"] = reasoning
        if tool_calls:
            entry["tool_calls"] = tool_calls
        return entry

    @staticmethod
    def _convert_user(content: list) -> list[dict]:
        """转换 user 消息的 content blocks → OpenAI 格式。

        tool_result block → tool 角色消息
        text block → user 角色消息
        """
        result = []
        for block in content:
            t = block.get("type", "")
            if t == "tool_result":
                c = block.get("content", "")
                if isinstance(c, list):
                    c = "\n".join(
                        b.get("text", "") for b in c if b.get("type") == "text"
                    )
                result.append({
                    "role": "tool",
                    "tool_call_id": block["tool_use_id"],
                    "content": str(c),
                })
            elif t == "text":
                result.append({"role": "user", "content": block["text"]})
        return result


class AnthropicToOpenAIToolConverter:
    """将 Anthropic tool schema 转换为 OpenAI function-calling 格式。"""

    @staticmethod
    def convert(tools: list[dict]) -> list[dict]:
        return [
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
