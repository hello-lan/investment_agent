import asyncio
import json
import uuid
from collections import Counter
from datetime import datetime
from typing import AsyncGenerator, Callable

from ...config import get_settings
from .models import ModelProvider, LLMResponse, ToolCall


class AgentEngine:
    def __init__(self, session_id: str, system_prompt: str = "", provider: ModelProvider | None = None):
        self.session_id = session_id
        self.task_id = str(uuid.uuid4())
        self.system_prompt = system_prompt
        self.provider = provider
        self.tools: list[dict] = []
        self.tool_handlers: dict[str, Callable] = {}
        self._interrupt = asyncio.Event()

        cfg = get_settings()["engine"]
        self.max_steps: int = cfg.get("max_steps", 30)
        self.slow_think_interval: int = cfg.get("slow_think_interval", 3)
        self.token_budget: int = cfg.get("token_budget", 100000)
        self.loop_threshold: int = cfg.get("loop_detection_threshold", 3)

        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def register_tool(self, schema: dict, handler: Callable) -> None:
        self.tools.append(schema)
        self.tool_handlers[schema["name"]] = handler

    def interrupt(self) -> None:
        self._interrupt.set()

    async def run(self, messages: list[dict]) -> AsyncGenerator[dict, None]:
        if not self.provider:
            yield {"type": "error", "message": "No model provider configured."}
            return

        step = 0
        recent_tool_calls: list[str] = []

        while step < self.max_steps:
            if self._interrupt.is_set():
                yield {"type": "interrupted", "step": step}
                break

            if self.total_input_tokens + self.total_output_tokens >= self.token_budget:
                yield {"type": "error", "message": f"Token budget ({self.token_budget}) exceeded."}
                break

            step += 1
            yield {"type": "step_start", "step": step}

            if step > 1 and step % self.slow_think_interval == 0:
                async for event in self._slow_think(messages, step):
                    yield event

            try:
                response: LLMResponse = await self.provider.chat(
                    messages=messages,
                    system=self.system_prompt,
                    tools=self.tools if self.tools else None,
                )
            except Exception as e:
                yield {"type": "error", "message": str(e)}
                break

            self.total_input_tokens += response.input_tokens
            self.total_output_tokens += response.output_tokens

            if response.content:
                yield {"type": "text_delta", "content": response.content}

            if not response.tool_calls:
                yield {
                    "type": "done",
                    "usage": {
                        "input_tokens": self.total_input_tokens,
                        "output_tokens": self.total_output_tokens,
                    },
                }
                messages.append({"role": "assistant", "content": response.content})
                break

            assistant_content = []
            if response.content:
                assistant_content.append({"type": "text", "text": response.content})
            for tc in response.tool_calls:
                assistant_content.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input})
            messages.append({"role": "assistant", "content": assistant_content})

            for tc in response.tool_calls:
                recent_tool_calls.append(tc.name)
            recent_tool_calls = recent_tool_calls[-self.loop_threshold * 2:]
            counts = Counter(recent_tool_calls[-self.loop_threshold:])
            if counts and counts.most_common(1)[0][1] >= self.loop_threshold:
                yield {"type": "error", "message": f"Dead loop detected: '{counts.most_common(1)[0][0]}' called {self.loop_threshold} times in a row."}
                break

            tool_results = []
            for tc in response.tool_calls:
                yield {"type": "tool_call", "tool": tc.name, "input": tc.input}
                result = await self._execute_tool(tc)
                yield {"type": "tool_result", "tool": tc.name, "output": result}
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": result,
                })

            messages.append({"role": "user", "content": tool_results})

        else:
            yield {"type": "error", "message": f"Max steps ({self.max_steps}) reached."}

    async def _execute_tool(self, tc: ToolCall) -> str:
        handler = self.tool_handlers.get(tc.name)
        if not handler:
            return f"Tool '{tc.name}' not found."
        try:
            result = await handler(**tc.input)
            return str(result)
        except Exception as e:
            return f"Tool error: {e}"

    async def _slow_think(self, messages: list[dict], step: int) -> AsyncGenerator[dict, None]:
        prompt = (
            f"[慢思考 @ step {step}] 请简要评估：\n"
            "1. 当前进度是否符合目标？\n"
            "2. 策略是否需要调整？\n"
            "3. 是否存在风险或偏离？\n"
            "请用1-3句话回答，不要调用工具。"
        )
        think_messages = messages + [{"role": "user", "content": prompt}]
        try:
            resp = await self.provider.chat(messages=think_messages, system=self.system_prompt)
            if resp.content:
                yield {"type": "slow_think", "content": resp.content}
        except Exception:
            pass
