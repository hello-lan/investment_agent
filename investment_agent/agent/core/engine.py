import asyncio
import json
import time
import uuid
from collections import Counter
from datetime import datetime
from typing import AsyncGenerator, Callable

from .models import ModelProvider, LLMResponse, ToolCall


class AgentEngine:
    """双循环执行引擎：快循环（LLM推理→工具调用→结果追加）+ 慢思考（定期全局复盘）"""

    def __init__(
        self,
        session_id: str,
        system_prompt: str = "",
        provider: ModelProvider | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        max_steps: int = 30,
        slow_think_interval: int = 3,
        token_budget: int = 100000,
        loop_detection_threshold: int = 3,
    ):
        self.session_id = session_id
        self.task_id = str(uuid.uuid4())
        self.system_prompt = system_prompt
        self.provider = provider
        self.tools: list[dict] = []
        self.tool_handlers: dict[str, Callable] = {}
        self._interrupt = asyncio.Event()

        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_steps = max_steps
        self.slow_think_interval = slow_think_interval
        self.token_budget = token_budget
        self.loop_threshold = loop_detection_threshold

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cache_read_tokens = 0
        self.total_cache_creation_tokens = 0

    def register_tool(self, schema: dict, handler: Callable) -> None:
        """注册工具：schema 给 LLM 看，handler 执行实际逻辑"""
        self.tools.append(schema)
        self.tool_handlers[schema["name"]] = handler

    def interrupt(self) -> None:
        """发送中断信号，优雅停止当前任务"""
        self._interrupt.set()

    LOOP_WHITELIST = {"run_command"}    # 允许连续调用的工具（不受死循环检测限制）

    async def run(self, messages: list[dict]) -> AsyncGenerator[dict, None]:
        """主执行循环：SSE 流式产出每一步的事件"""
        if not self.provider:
            yield {"type": "error", "message": "No model provider configured."}
            return

        step = 0
        recent_tool_calls: list[str] = []  # 滑动窗口记录最近调用的工具

        while step < self.max_steps:
            # —— 安全检查 ——
            if self._interrupt.is_set():
                yield {"type": "interrupted", "step": step}
                break

            if self.total_input_tokens + self.total_output_tokens >= self.token_budget:
                yield {"type": "error", "message": f"Token budget ({self.token_budget}) exceeded."}
                break

            step += 1
            yield {"type": "step_start", "step": step}

            # —— 慢思考：每 N 步触发一次全局复盘 ——
            if step > 1 and step % self.slow_think_interval == 0:
                async for event in self._slow_think(messages, step):
                    yield event

            # —— 快循环：LLM 推理 ——
            try:
                yield {
                    "type": "llm_request",
                    "step": step,
                    "messages": messages,
                }
                chat_kwargs: dict = {
                    "messages": self.provider._convert_messages(messages),
                    "system": self.system_prompt,
                    "tools": self.tools if self.tools else None,
                }
                if self.temperature is not None:
                    chat_kwargs["temperature"] = self.temperature
                if self.max_tokens is not None:
                    chat_kwargs["max_tokens"] = self.max_tokens
                response: LLMResponse = await self.provider.chat(**chat_kwargs)
            except Exception as e:
                yield {"type": "error", "message": str(e)}
                break

            self.total_input_tokens += response.input_tokens
            self.total_output_tokens += response.output_tokens
            self.total_cache_read_tokens += response.cache_read_tokens
            self.total_cache_creation_tokens += response.cache_creation_tokens

            yield {
                "type": "llm_response",
                "step": step,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cache_read_tokens": response.cache_read_tokens,
                "cache_creation_tokens": response.cache_creation_tokens,
                "content": response.content or "",
                "reasoning": response.reasoning_content or "",
                "tool_calls": [{"name": tc.name, "input": tc.input} for tc in (response.tool_calls or [])],
            }

            # 输出文本增量
            if response.content:
                yield {"type": "text_delta", "content": response.content}

            # 无工具调用 → 任务结束
            if not response.tool_calls:
                yield {
                    "type": "done",
                    "usage": {
                        "input_tokens": self.total_input_tokens,
                        "output_tokens": self.total_output_tokens,
                        "cache_read_tokens": self.total_cache_read_tokens,
                        "cache_creation_tokens": self.total_cache_creation_tokens,
                    },
                }
                # 构造 assistant 消息（兼容 Anthropic 的 content block 格式）
                if response.reasoning_content or response.extra_blocks:
                    assistant_blocks = []
                    if response.reasoning_content:
                        assistant_blocks.append({"type": "reasoning", "content": response.reasoning_content})
                    assistant_blocks.extend(response.extra_blocks)
                    if response.content:
                        assistant_blocks.append({"type": "text", "text": response.content})
                    messages.append({"role": "assistant", "content": assistant_blocks})
                else:
                    messages.append({"role": "assistant", "content": response.content})
                break

            # 有工具调用 → 构造 assistant 消息并执行工具
            assistant_content = []
            if response.reasoning_content:
                assistant_content.append({"type": "reasoning", "content": response.reasoning_content})
            if response.extra_blocks:
                assistant_content.extend(response.extra_blocks)
            if response.content:
                assistant_content.append({"type": "text", "text": response.content})
            for tc in response.tool_calls:
                assistant_content.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input})
            messages.append({"role": "assistant", "content": assistant_content})

            # —— 死循环检测：同一工具连续调用超过阈值则中止 ——
            for tc in response.tool_calls:
                recent_tool_calls.append(tc.name)
            loop_candidates = [n for n in recent_tool_calls if n not in self.LOOP_WHITELIST]
            recent_tool_calls = recent_tool_calls[-self.loop_threshold * 2:]  # 保持滑动窗口
            counts = Counter(loop_candidates[-self.loop_threshold:])
            if counts and counts.most_common(1)[0][1] >= self.loop_threshold:
                yield {
                    "type": "error",
                    "message": f"Dead loop detected: '{counts.most_common(1)[0][0]}' called {self.loop_threshold} times in a row.",
                    "recent_tool_calls": list(recent_tool_calls),
                }
                break

            # —— 执行工具 ——
            tool_results = []
            for tc in response.tool_calls:
                yield {"type": "tool_call", "tool": tc.name, "input": tc.input}
                t0 = time.monotonic()
                result = await self._execute_tool(tc)
                duration_ms = int((time.monotonic() - t0) * 1000)
                yield {"type": "tool_result", "tool": tc.name, "output": result, "duration_ms": duration_ms}
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": result,
                })

            # 工具结果作为 user 消息追加到上下文
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
            think_kwargs: dict = {"messages": think_messages, "system": self.system_prompt}
            if self.temperature is not None:
                think_kwargs["temperature"] = self.temperature
            if self.max_tokens is not None:
                think_kwargs["max_tokens"] = self.max_tokens
            resp = await self.provider.chat(**think_kwargs)
            if resp.content:
                yield {"type": "slow_think", "content": resp.content}
        except Exception:
            pass
