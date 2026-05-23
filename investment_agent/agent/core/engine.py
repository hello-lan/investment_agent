import asyncio
import json
import time
import uuid
from collections import Counter
from datetime import datetime
from typing import AsyncGenerator, Callable

from .models import ModelProvider, LLMResponse, ToolCall
from ..context.runtime_trimmer import RuntimeTrimmer, NoOpRuntimeTrimmer


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
        context_trim_interval: int = 0,
        tool_trim_limits: dict | None = None,
        runtime_trimmer: RuntimeTrimmer | None = None,
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
        self.context_trim_interval = context_trim_interval  # 0 = disabled
        self.tool_trim_limits = tool_trim_limits or {}
        self._runtime_trimmer = runtime_trimmer

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cache_read_tokens = 0
        self.total_cache_creation_tokens = 0

        self._orch_dependencies: set[str] = set()  # orch skill 的子技能名称集合
        self._messages: list[dict] = []             # 当前步骤的消息列表快照
        self._subagent_queue: asyncio.Queue | None = None  # 子Agent实时事件队列

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
            self._messages = messages
            yield {"type": "step_start", "step": step}

            # —— 运行时上下文整理：每 N 步裁剪旧消息 ——
            if self._runtime_trimmer is not None and self.context_trim_interval > 0 and step > 1 and step % self.context_trim_interval == 0:
                messages = self._runtime_trimmer.trim(messages, step)
                yield {"type": "context_trim", "step": step}

            # —— 慢思考：每 N 步触发一次全局复盘 ——
            if self.slow_think_interval > 0 and step > 1 and step % self.slow_think_interval == 0:
                reflection = await self._do_slow_think(messages, step)
                if reflection:
                    yield {"type": "slow_think", "content": reflection}
                    messages.append(
                        {"role": "user", "content": f"[慢思考反思 @ step {step}] {reflection}"}
                    )

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
                        assistant_blocks.append({"type": "reasoning", "content": self._truncate_reasoning(response.reasoning_content)})
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
                assistant_content.append({"type": "reasoning", "content": self._truncate_reasoning(response.reasoning_content)})
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
                # 子Agent在后台运行时，实时转发其进度事件
                if result is None:
                    while self._subagent_queue is not None:
                        event = await self._subagent_queue.get()
                        if event["type"] == "__subagent_done__":
                            result = event["result"]
                            self._subagent_queue = None
                            break
                        elif event["type"] == "__subagent_error__":
                            result = f"子任务执行错误: {event['message']}"
                            self._subagent_queue = None
                            break
                        else:
                            yield event
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

    async def _execute_tool(self, tc: ToolCall) -> str | None:
        # —— 透明 SubAgent：orch 依赖的子技能在隔离引擎中执行 ——
        if tc.name == "Skill":
            skill_name = tc.input.get("name", "")
            if skill_name in self._orch_dependencies:
                self._start_subagent(skill_name)
                return None  # 信号：子Agent在后台运行，主循环需轮询 _subagent_queue

        handler = self.tool_handlers.get(tc.name)
        if not handler:
            return f"Tool '{tc.name}' not found."
        try:
            result = await handler(**tc.input)

            # —— 检测 orch skill 加载，记录其依赖 ——
            if tc.name == "Skill":
                skill_name = tc.input.get("name", "")
                from ..skills.loader import get_skill
                skill = get_skill(skill_name)
                if skill and skill.skill_type == "orch" and skill.depends_on:
                    for dep in skill.depends_on:
                        self._orch_dependencies.add(dep)

            return str(result)
        except Exception as e:
            return f"Tool error: {e}"

    def _start_subagent(self, skill_name: str) -> None:
        """启动子Agent后台任务，事件通过 _subagent_queue 实时转发。"""
        queue: asyncio.Queue = asyncio.Queue()
        self._subagent_queue = queue
        asyncio.ensure_future(self._run_subagent_task(skill_name, queue))

    async def _run_subagent_task(self, skill_name: str, queue: asyncio.Queue) -> None:
        """子Agent后台任务：运行隔离引擎，事件入队，完成/错误时发哨兵事件。"""
        from ..skills.loader import get_skill
        from ..skills.cache import get_cache
        from ..tools.run_command import RunCommandTool

        skill = get_skill(skill_name)
        if not skill:
            await queue.put({"type": "__subagent_error__", "message": f"Skill '{skill_name}' not found."})
            return

        cache = get_cache()
        body = cache.get(skill_name, skill.main_md_path, skill.skill_dir)

        # 构造子Agent消息（不含原始用户请求，避免子Agent误判任务范围）
        sub_messages: list[dict] = []
        for m in reversed(self._messages):
            if m.get("role") == "assistant":
                text = self._extract_text_from_content(m.get("content", ""))
                if text.strip():
                    sub_messages.append({"role": "user", "content": text})
                break
        sub_messages.append({"role": "user", "content": (
            "你是一个子Agent，负责执行上述步骤。\n\n"
            "关键规则：\n"
            "1. 你已拥有完整的技能说明（system prompt），直接使用其中指令\n"
            "2. 不要加载 Skill 或编排技能\n"
            "3. 直接执行任务并返回结果，不要询问确认\n"
            "4. 只使用 run_command 工具执行具体操作"
        )})

        sub = AgentEngine(
            session_id=f"sub_{uuid.uuid4().hex[:8]}",
            system_prompt=body,
            provider=self.provider,
            max_steps=self.max_steps,
            slow_think_interval=0,
            token_budget=self.token_budget,
            context_trim_interval=0,
            runtime_trimmer=NoOpRuntimeTrimmer(),
        )
        run_tool = RunCommandTool()
        sub.register_tool(run_tool.schema, run_tool.run)

        result_text = ""
        try:
            async for event in sub.run(sub_messages):
                if event["type"] == "text_delta":
                    result_text += event["content"]
                elif event["type"] in ("tool_call", "tool_result"):
                    await queue.put({
                        "type": f"sub_{event['type']}",
                        "tool": event.get("tool", ""),
                        "input": str(event.get("input", "")),
                        "output": str(event.get("output", "")),
                        "duration_ms": event.get("duration_ms", 0),
                    })
                elif event["type"] == "error":
                    await queue.put({"type": "__subagent_error__", "message": event["message"]})
                    return
                elif event["type"] == "done":
                    break
        except Exception as e:
            await queue.put({"type": "__subagent_error__", "message": str(e)})
            return

        # 子引擎 token 计入主引擎
        self.total_input_tokens += sub.total_input_tokens
        self.total_output_tokens += sub.total_output_tokens
        self.total_cache_read_tokens += sub.total_cache_read_tokens
        self.total_cache_creation_tokens += sub.total_cache_creation_tokens

        await queue.put({
            "type": "__subagent_done__",
            "result": result_text.strip() or "(子任务完成，无文本输出)",
        })

    @staticmethod
    def _extract_text_from_content(content) -> str:
        """从 Anthropic content blocks 中提取纯文本。"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif block.get("type") == "reasoning":
                        parts.append(block.get("content", ""))
            return "\n".join(parts)
        return str(content)

    def _extract_role_from_system(self) -> str:
        """从 system_prompt 中提取角色定义（第一段），用于慢思考的精简 system。

        截取到第一个 ``\n\n`` 或 ``##`` 标记为止，最多 200 字符。
        """
        prompt = self.system_prompt or ""
        if isinstance(prompt, list):
            # Anthropic cache_control 格式：取第一个 text block
            for block in prompt:
                if isinstance(block, dict) and block.get("type") == "text":
                    prompt = block.get("text", "")
                    break
            else:
                return "请基于对话历史评估当前任务进展是否正常。"

        # 截取到第一个段落分隔符或 Markdown 标题
        for marker in ("\n\n", "\n##", "\n# "):
            idx = prompt.find(marker)
            if idx != -1:
                prompt = prompt[:idx]
                break

        prompt = prompt.strip()
        if len(prompt) > 200:
            prompt = prompt[:200].rsplit("。", 1)[0] + "。"
        return prompt + " 请基于对话历史评估当前任务进展是否正常。"

    @staticmethod
    def _truncate_reasoning(content: str, max_chars: int = 300) -> str:
        """截断推理内容：短于 max_chars 完整保留，否则保留首尾各一半。"""
        if len(content) <= max_chars:
            return content
        half = max_chars // 2
        return content[:half] + "\n...[推理已截断]...\n" + content[-half:]

    async def _do_slow_think(self, messages: list[dict], step: int) -> str | None:
        """慢思考：仅发送最近消息 + 精简 system prompt，检查是否跑偏。

        返回反思文本供调用方注入 messages，实现真正的课程纠正。
        """
        import logging
        _log = logging.getLogger(__name__)

        # 构建精简消息列表：原始用户问题 + 最近 5 轮
        slim_messages = [messages[0]]  # 原始用户问题
        # 从尾部取最近 5 条 assistant 消息及其后的 tool_result
        assistant_positions = [
            i for i, m in enumerate(messages) if m.get("role") == "assistant"
        ]
        keep_from = assistant_positions[-(5)] if len(assistant_positions) >= 5 else (
            assistant_positions[0] if assistant_positions else 0
        )
        slim_messages.extend(messages[keep_from:])

        prompt = (
            f"[慢思考 @ step {step}] 请简要评估：\n"
            "1. 当前进度是否符合目标？\n"
            "2. 策略是否需要调整？\n"
            "3. 是否存在风险或偏离？\n"
            "请用1-3句话回答，不要调用工具。"
        )
        slim_messages.append({"role": "user", "content": prompt})

        # 精简 system prompt：从实际 system_prompt 中提取角色定义（第一段或前200字符）
        minimal_system = self._extract_role_from_system()

        try:
            think_kwargs: dict = {
                "messages": self.provider._convert_messages(slim_messages),
                "system": minimal_system,
            }
            if self.temperature is not None:
                think_kwargs["temperature"] = self.temperature
            if self.max_tokens is not None:
                think_kwargs["max_tokens"] = min(self.max_tokens, 512)
            else:
                think_kwargs["max_tokens"] = 512
            resp = await self.provider.chat(**think_kwargs)
            self.total_input_tokens += resp.input_tokens
            self.total_output_tokens += resp.output_tokens
            if resp.content:
                return resp.content.strip()
        except Exception:
            _log.warning("Slow think failed at step %d", step, exc_info=True)

        return None
