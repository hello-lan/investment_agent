"""双循环执行引擎：快循环 + 慢思考。"""

from typing import AsyncGenerator

from ._signals import _Value
from ..constants import EventType
from .base_loop import BaseLoopEngine
from .slow_think import SlowThinkStrategy
from .provider import ToolCall


class DualLoopEngine(BaseLoopEngine):
    """当前默认执行循环：ReAct 主循环 + 慢思考纠偏层。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._slow_think = SlowThinkStrategy()

    async def maybe_pre_llm_phase(self, messages: list[dict], step: int) -> AsyncGenerator:
        trigger = self._slow_think.should_think(
            step, self.max_steps, self.slow_think_interval,
        )
        if trigger:
            reflection, *token_updates = await self._slow_think.think(
                messages, step, self.provider,
                extract_role_fn=self._extract_role_from_system,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                slow_think_max_tokens=self.SLOW_THINK_MAX_TOKENS,
                total_input_tokens=self.total_input_tokens,
                total_output_tokens=self.total_output_tokens,
                total_cache_read_tokens=self.total_cache_read_tokens,
                total_cache_creation_tokens=self.total_cache_creation_tokens,
            )
            (self.total_input_tokens, self.total_output_tokens,
             self.total_cache_read_tokens, self.total_cache_creation_tokens) = token_updates

            if reflection:
                yield {
                    "type": EventType.SLOW_THINK,
                    "content": reflection,
                    "trigger": trigger,
                }
                messages.append({
                    "role": "user",
                    "content": f"[慢思考反思 @ step {step}] {reflection}",
                })

        yield _Value(messages)

    def on_tool_calls_received(self, tool_calls: list[ToolCall]) -> None:
        self._slow_think.record_tool_result(
            has_error=False,
            tool_names=[tc.name for tc in tool_calls],
        )

    def on_tool_results(self, tool_calls: list[ToolCall], has_error: bool) -> None:
        self._slow_think.record_tool_result(
            has_error=has_error,
            tool_names=[tc.name for tc in tool_calls],
        )
