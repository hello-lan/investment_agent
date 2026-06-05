"""OpenAI Chat Completions 响应解析器。

从 OpenAICompatProvider.chat() 中提取，将原始 OpenAI API 响应
解析为统一的 LLMResponse 数据结构，独立可测试。
"""

from __future__ import annotations

import json
import logging

from .types import LLMResponse, ToolCall

_log = logging.getLogger(__name__)


class OpenAIResponseParser:
    """解析 OpenAI Chat Completions 响应为统一的 LLMResponse。

    封装：content 提取、tool call JSON 解析、finish_reason 映射、
    缓存指标提取（兼容 DeepSeek / OpenAI 两种格式）。
    """

    @staticmethod
    def parse(resp, model_name: str) -> LLMResponse:
        """解析 OpenAI Chat Completions API 响应。

        Args:
            resp: OpenAI ChatCompletion 对象
            model_name: 模型名称（用于日志）

        Returns:
            统一的 LLMResponse
        """
        msg = resp.choices[0].message

        content = msg.content or ""
        reasoning = getattr(msg, "reasoning_content", None) or None

        # 解析 tool_calls
        tool_calls: list[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    _log.warning(
                        "Skipping malformed tool call arguments from model %s: %s",
                        model_name, tc.function.arguments[:200],
                    )
                    continue
                tool_calls.append(ToolCall(
                    id=tc.id, name=tc.function.name, input=args,
                ))

        # 映射 finish_reason
        raw_reason = resp.choices[0].finish_reason or "end_turn"
        stop_reason = OpenAIResponseParser._map_stop_reason(
            raw_reason, tool_calls, model_name
        )

        # 提取缓存指标
        cache_read, cache_creation = OpenAIResponseParser._extract_cache_metrics(resp)

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

    # ── helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _map_stop_reason(
        raw_reason: str, tool_calls: list[ToolCall], model_name: str,
    ) -> str:
        """映射 OpenAI finish_reason → 统一 stop_reason。"""
        from ..constants import StopReason

        if raw_reason == "stop":
            return StopReason.END_TURN
        if raw_reason == "tool_calls":
            return StopReason.TOOL_USE
        if raw_reason == "length":
            # max_tokens 耗尽时 tool_calls 可能不完整 → 丢弃
            if tool_calls:
                _log.warning(
                    "Response truncated (finish_reason=length), "
                    "discarding %d tool calls",
                    len(tool_calls),
                )
                tool_calls.clear()
            return StopReason.LENGTH
        return raw_reason

    @staticmethod
    def _extract_cache_metrics(resp) -> tuple[int, int]:
        """提取缓存命中指标，兼容 DeepSeek 和 OpenAI 两种格式。

        DeepSeek: usage.prompt_cache_hit_tokens / prompt_cache_miss_tokens
        OpenAI:   usage.prompt_tokens_details.cached_tokens
        """
        cache_read = 0
        cache_creation = 0
        if not resp.usage:
            return 0, 0

        # DeepSeek 格式
        cache_read = getattr(resp.usage, 'prompt_cache_hit_tokens', 0) or 0
        cache_creation = getattr(resp.usage, 'prompt_cache_miss_tokens', 0) or 0

        # OpenAI 格式（仅在 DeepSeek 无数据时尝试）
        if not cache_read:
            details = getattr(resp.usage, 'prompt_tokens_details', None)
            if details:
                cache_read = getattr(details, 'cached_tokens', 0) or 0

        return cache_read, cache_creation
