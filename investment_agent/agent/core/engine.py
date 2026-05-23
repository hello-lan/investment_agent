import asyncio
import json
import logging
import time
import uuid
from collections import Counter
from datetime import datetime
from typing import AsyncGenerator, Callable

from .models import ModelProvider, LLMResponse, ToolCall
from ..config import SUBAGENT_SYSTEM_PROMPT
from ..context.runtime_trimmer import RuntimeTrimmer, NoOpRuntimeTrimmer

_log = logging.getLogger(__name__)


class SubAgentPool:
    """子Agent并发池：asyncio.Semaphore 控制同层并发数。

    Phase 2 新增：用于管理多个 DelegateTask 的并发执行。
    每层 Agent 拥有独立的 pool（独立 semaphore），不存在跨层死锁。
    """

    def __init__(self, max_concurrent: int):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active: dict[str, asyncio.Task] = {}

    async def submit(self, delegate_id: str, coro) -> asyncio.Task:
        """提交子Agent任务，受信号量控制。"""
        await self._semaphore.acquire()
        task = asyncio.create_task(self._wrap(delegate_id, coro))
        self._active[delegate_id] = task
        return task

    async def _wrap(self, delegate_id: str, coro):
        """包装协程：完成后释放信号量。"""
        try:
            return await coro
        finally:
            self._semaphore.release()
            self._active.pop(delegate_id, None)


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
        subagent_depth: int = 0,
        max_subagent_depth: int = 3,
        max_concurrent_subagents: int = 3,
        sub_agent_mode: str = "serial",
    ):
        self.session_id = session_id
        self.task_id = str(uuid.uuid4())
        self._system_prompt = system_prompt
        self.provider = provider
        self.tools: list[dict] = []
        self.tool_handlers: dict[str, Callable] = {}
        self._skills: list = []
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

        # ── 子Agent配置 ──
        self.subagent_depth = subagent_depth              # 当前嵌套深度（根=0）
        self.max_subagent_depth = max_subagent_depth      # 最大嵌套深度
        self.max_concurrent_subagents = max_concurrent_subagents  # 同层最大并发
        self.sub_agent_mode = sub_agent_mode              # "serial" | "concurrent"
        self._subagent_pool: SubAgentPool | None = None   # 延迟初始化（仅 concurrent 模式使用）

        self._messages: list[dict] = []             # 当前步骤的消息列表快照

    def register_tool(self, schema: dict, handler: Callable) -> None:
        """注册工具：schema 给 LLM 看，handler 执行实际逻辑"""
        self.tools.append(schema)
        self.tool_handlers[schema["name"]] = handler

    def register_skill(self, skill) -> None:
        """注册技能：记录 skill 对象，供 system_prompt property 拼接 prompt"""
        self._skills.append(skill)

    @property
    def system_prompt(self) -> str:
        """动态拼接：基础 prompt + 项目路径 + 已注册 skill 的名称/描述"""
        prompt = self._system_prompt

        # 追加项目路径信息（固定部分，始终注入）
        if "## 项目路径" not in prompt:
            from ...config import PROJECT_ROOT
            prompt += (
                f"\n\n## 项目路径\n\n"
                f"PROJECT_ROOT = {PROJECT_ROOT}\n\n"
                f"## 当前时间\n"
                f"{datetime.now()}\n"
            )

        if not self._skills:
            return prompt
        if "# 可用技能" in prompt:
            return prompt
        lines = []
        for s in self._skills:
            prefix = "[orch] " if s.skill_type == "orch" else ""
            deps = f"（含 {len(s.depends_on)} 个子流程）" if s.depends_on else ""
            lines.append(f"- {prefix}**{s.name}**: {s.description}{deps}")
        return (
            prompt
            + "\n\n---\n\n# 可用技能\n\n"
            + "\n".join(lines)
            + "\n\n> 使用 Skill 工具加载技能完整说明后再执行。"
        )

    @system_prompt.setter
    def system_prompt(self, value: str) -> None:
        self._system_prompt = value

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

            # 无工具调用 → 任务结束（除非因 max_tokens 耗尽被截断）
            if not response.tool_calls:
                if response.stop_reason == "length":
                    # 输出被截断，注入"继续"提示让模型从断开处恢复
                    if response.content:
                        assistant_msg = {"role": "assistant", "content": response.content}
                        messages.append(assistant_msg)
                    messages.append({
                        "role": "user",
                        "content": "你的上一次回复因达到token上限被截断，请继续完成未完成的部分。",
                    })
                    yield {"type": "text_delta", "content": "\n\n[输出被截断，自动请求继续...]\n\n"}
                    continue

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
            # Phase 2: 并发模式下，如果包含 DelegateTask，走并发路径
            if self.sub_agent_mode == "concurrent" and any(
                tc.name == "DelegateTask" for tc in response.tool_calls
            ):
                tool_results = []
                async for event in self._execute_tools_concurrent(response.tool_calls):
                    if event.get("_internal_result"):
                        tool_results = event["_internal_result"]
                    else:
                        yield event
            else:
                tool_results = []
                async for event in self._execute_tools_serial(response.tool_calls):
                    if event.get("_internal_result"):
                        tool_results = event["_internal_result"]
                    else:
                        yield event

            # 工具结果作为 user 消息追加到上下文
            messages.append({"role": "user", "content": tool_results})

        else:
            yield {"type": "error", "message": f"Max steps ({self.max_steps}) reached."}

    async def _execute_tool(self, tc: ToolCall) -> str:
        """执行单个工具调用（DelegateTask 由主循环处理，不经过此方法）"""
        handler = self.tool_handlers.get(tc.name)
        if not handler:
            return f"Tool '{tc.name}' not found."
        try:
            result = await handler(**tc.input)
            return str(result)
        except Exception as e:
            return f"Tool error: {e}"

    async def _execute_tools_serial(self, tool_calls: list[ToolCall]):
        """串行执行工具列表（Phase 1 逻辑提取为独立方法）。

        DelegateTask 逐个执行，阻塞等待完成。
        非 DelegateTask 直接调用 _execute_tool。
        最终结果通过 _internal_result 事件返回。
        """
        tool_results = []
        for tc in tool_calls:
            yield {"type": "tool_call", "tool": tc.name, "input": tc.input}
            t0 = time.monotonic()

            if tc.name == "DelegateTask":
                if self.subagent_depth >= self.max_subagent_depth:
                    result = (
                        f"错误：已达到最大委派深度 {self.max_subagent_depth}，"
                        f"无法创建子Agent"
                    )
                else:
                    raw_skill_names = tc.input.get("skill_names", []) or []
                    task_desc = tc.input.get("task", "")
                    from ..skills.loader import _registry as skill_registry
                    skill_names = [
                        n for n in raw_skill_names
                        if skill_registry.get(n) and skill_registry[n].skill_type != "orch"
                    ]
                    prompt = await self._generate_task_instruction(task_desc, skill_names)
                    delegate_id = f"delegate_{uuid.uuid4().hex[:8]}"
                    event_queue = asyncio.Queue()
                    asyncio.ensure_future(
                        self._run_subagent_task(
                            skill_names, prompt, event_queue, delegate_id
                        )
                    )
                    result = ""
                    while True:
                        event = await event_queue.get()
                        if event["type"] == "__delegate_done__":
                            result = event["result"]
                            break
                        elif event["type"] == "__delegate_error__":
                            result = f"子任务执行错误: {event['message']}"
                            break
                        else:
                            yield event
            else:
                result = await self._execute_tool(tc)

            duration_ms = int((time.monotonic() - t0) * 1000)
            yield {
                "type": "tool_result",
                "tool": tc.name,
                "output": result,
                "duration_ms": duration_ms,
            }
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": result,
            })
        yield {"_internal_result": tool_results}

    async def _execute_tools_concurrent(self, tool_calls: list[ToolCall]):
        """并发执行工具列表（Phase 2）。

        DelegateTask 通过 SubAgentPool 并发启动，非 DelegateTask 顺序执行。
        共享 event_queue 收集所有 delegate 的实时事件，统一转发。
        结果按原始顺序返回，通过 _internal_result 事件返回。
        """
        # 延迟初始化 pool
        if self._subagent_pool is None:
            self._subagent_pool = SubAgentPool(self.max_concurrent_subagents)

        event_queue = asyncio.Queue()
        delegate_tasks = []  # [(idx, tc, asyncio.Task, result_queue, t0)]
        ordered_results = [None] * len(tool_calls)

        # 第一遍：分离 delegate 和非 delegate
        for idx, tc in enumerate(tool_calls):
            yield {"type": "tool_call", "tool": tc.name, "input": tc.input}
            t0 = time.monotonic()

            if tc.name == "DelegateTask":
                if self.subagent_depth >= self.max_subagent_depth:
                    result = (
                        f"错误：已达到最大委派深度 {self.max_subagent_depth}，"
                        f"无法创建子Agent"
                    )
                    yield {
                        "type": "tool_result",
                        "tool": tc.name,
                        "output": result,
                        "duration_ms": int((time.monotonic() - t0) * 1000),
                    }
                    ordered_results[idx] = {
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": result,
                    }
                    continue

                raw_skill_names = tc.input.get("skill_names", []) or []
                task_desc = tc.input.get("task", "")
                from ..skills.loader import _registry as skill_registry
                skill_names = [
                    n for n in raw_skill_names
                    if skill_registry.get(n) and skill_registry[n].skill_type != "orch"
                ]
                prompt = await self._generate_task_instruction(task_desc, skill_names)
                delegate_id = f"delegate_{uuid.uuid4().hex[:8]}"
                result_queue = asyncio.Queue()
                task = await self._subagent_pool.submit(
                    delegate_id,
                    self._run_subagent_task(
                        skill_names, prompt, event_queue, delegate_id, result_queue
                    ),
                )
                delegate_tasks.append((idx, tc, task, result_queue, t0))
            else:
                # 非 delegate：顺序执行
                result = await self._execute_tool(tc)
                duration_ms = int((time.monotonic() - t0) * 1000)
                yield {
                    "type": "tool_result",
                    "tool": tc.name,
                    "output": result,
                    "duration_ms": duration_ms,
                }
                ordered_results[idx] = {
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": result,
                }

        # 第二遍：转发实时事件直到所有 delegate 完成
        done_count = 0
        while done_count < len(delegate_tasks):
            event = await event_queue.get()
            if event["type"] == "__delegate_done__":
                done_count += 1
            elif event["type"] == "__delegate_error__":
                done_count += 1
                yield event
            else:
                yield event

        # 第三遍：按原始顺序收集结果
        for idx, tc, task, result_queue, t0 in delegate_tasks:
            await task  # 确保完成
            result_event = await result_queue.get()
            if result_event["type"] == "__delegate_done__":
                result = result_event["result"]
            else:
                result = f"子任务执行错误: {result_event['message']}"
            duration_ms = int((time.monotonic() - t0) * 1000)
            yield {
                "type": "tool_result",
                "tool": tc.name,
                "output": result,
                "duration_ms": duration_ms,
                "delegate_id": result_event.get("delegate_id", ""),
            }
            ordered_results[idx] = {
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": result,
            }

        yield {"_internal_result": ordered_results}

    async def _generate_task_instruction(self, task: str, skill_names: list[str]) -> str:
        """基于对话上下文为子Agent生成聚焦的任务指令。

        使用轻量 LLM 调用提炼父Agent的对话上下文，生成适合子Agent的任务说明。
        失败时 fallback 到 LLM 传入的原始 task 描述。
        """

        if not self._messages:
            return task

        # 构建精简纯文本消息：提取文本内容，丢弃 tool_use/tool_result blocks，
        # 避免 OpenAI 兼容 Provider 因 tool pair 不完整而报错 (400 Bad Request)
        # 取首条用户问题 + 最近5条（去重避免重叠）
        def _msg_text(msg: dict) -> dict | None:
            role = msg.get("role", "")
            text = self._extract_text_from_content(msg.get("content", ""))
            return {"role": role, "content": text} if text.strip() else None

        text_messages: list[dict] = []
        seen = {0}  # 首条必取
        t = _msg_text(self._messages[0])
        if t:
            text_messages.append(t)
        tail_start = max(1, len(self._messages) - 5)
        for i in range(tail_start, len(self._messages)):
            if i not in seen:
                t = _msg_text(self._messages[i])
                if t:
                    text_messages.append(t)

        skill_info = f"将使用技能: {', '.join(skill_names)}" if skill_names else "无指定技能"
        prompt = (
            f"你是一个任务规划者。请基于以下对话上下文，为子Agent生成一条聚焦的任务指令。\n\n"
            f"父Agent要求: {task}\n"
            f"{skill_info}\n\n"
            f"要求：\n"
            f"1. 从对话上下文中提取子Agent执行所需的关键信息（如股票代码、文件路径、年份等）\n"
            f"2. 明确说明输入和期望输出\n"
            f"3. 不要添加多余的解释，直接输出任务指令\n"
            f"4. 用中文输出"
        )
        text_messages.append({"role": "user", "content": prompt})

        try:
            kwargs: dict = {
                "messages": text_messages,
                "system": "你是一个任务规划助手，负责为子Agent生成精确的任务指令。",
            }
            if self.temperature is not None:
                kwargs["temperature"] = self.temperature
            if self.max_tokens is not None:
                kwargs["max_tokens"] = min(self.max_tokens, 256)
            else:
                kwargs["max_tokens"] = 256
            resp = await self.provider.chat(**kwargs)
            self.total_input_tokens += resp.input_tokens
            self.total_output_tokens += resp.output_tokens
            if resp.content:
                return resp.content.strip()
        except Exception:
            _log.warning("Task instruction generation failed, using fallback", exc_info=True)

        return task

    async def _run_subagent_task(
        self,
        skill_names: list[str],
        prompt: str,
        event_queue: asyncio.Queue,
        delegate_id: str,
        result_queue: asyncio.Queue | None = None,
    ) -> None:
        """子Agent后台任务：运行隔离引擎，事件入队，完成/错误时发哨兵事件。

        支持嵌套委派：子引擎可注册 DelegateTask 工具，进一步创建孙Agent。
        事件前缀根据嵌套深度自动累加（depth=1: sub_tool_call, depth=2: sub_sub_tool_call）。

        Args:
            result_queue: 并发模式下用于接收完成/错误信号（与 event_queue 分离）。
                         串行模式下为 None，完成/错误信号写入 event_queue。
        """
        from ..skills.tool import SkillTool
        from ..skills.loader import _registry as skill_registry
        from ..tools.run_command import RunCommandTool
        from ..tools.registry import get_tool

        depth = self.subagent_depth + 1
        # 完成/错误信号的目标队列
        signal_queue = result_queue if result_queue is not None else event_queue

        sub = AgentEngine(
            session_id=f"sub_{delegate_id}",
            system_prompt=SUBAGENT_SYSTEM_PROMPT,
            provider=self.provider,
            max_steps=self.max_steps,
            slow_think_interval=0,
            token_budget=self.token_budget,
            context_trim_interval=0,
            runtime_trimmer=NoOpRuntimeTrimmer(),
            subagent_depth=depth,
            max_subagent_depth=self.max_subagent_depth,
            max_concurrent_subagents=self.max_concurrent_subagents,
            sub_agent_mode=self.sub_agent_mode,
        )
        # 注册基础工具
        run_tool = RunCommandTool()
        sub.register_tool(run_tool.schema, run_tool.run)
        skill_tool = SkillTool()
        sub.register_tool(skill_tool.schema, skill_tool.run)
        # 始终注册 DelegateTask（深度未达上限时允许嵌套委派）
        if depth < self.max_subagent_depth:
            delegate_tool = get_tool("DelegateTask")
            if delegate_tool:
                sub.register_tool(delegate_tool.schema, delegate_tool.run)
        # 注册父Agent传入的技能 → body 自动注入 sub.system_prompt
        for name in skill_names:
            skill = skill_registry.get(name)
            if skill:
                sub.register_skill(skill)

        # 构造子Agent消息（仅包含任务指令，规则已在 system_prompt 中）
        sub_messages: list[dict] = [
            {"role": "user", "content": prompt},
        ]

        # 事件前缀：depth=1 → "sub_", depth=2 → "sub_sub_"
        prefix = "sub_" * depth

        result_text = ""
        try:
            async for event in sub.run(sub_messages):
                event_type = event["type"]
                if event_type == "text_delta":
                    result_text += event["content"]
                    await event_queue.put({
                        "type": f"{prefix}text_delta",
                        "delegate_id": delegate_id,
                        "depth": depth,
                        "content": event["content"],
                    })
                elif event_type in ("tool_call", "tool_result"):
                    # 嵌套子事件已有前缀（如 sub_tool_call），再加一层前缀形成累积
                    sub_type = event.get("type", "")
                    if sub_type.startswith("sub_"):
                        # 嵌套子事件：在已有前缀上再加一层
                        forwarded_type = f"{prefix}{sub_type}"
                    else:
                        forwarded_type = f"{prefix}{sub_type}"
                    forwarded = {
                        "type": forwarded_type,
                        "delegate_id": event.get("delegate_id", delegate_id),
                        "depth": event.get("depth", depth),
                        "tool": event.get("tool", ""),
                        "duration_ms": event.get("duration_ms", 0),
                    }
                    if "input" in event:
                        forwarded["input"] = str(event["input"])
                    if "output" in event:
                        forwarded["output"] = str(event["output"])
                    await event_queue.put(forwarded)
                elif event_type == "error":
                    await signal_queue.put({
                        "type": "__delegate_error__",
                        "delegate_id": delegate_id,
                        "message": event["message"],
                    })
                    return
                elif event_type == "done":
                    break
                elif event_type.startswith("sub_"):
                    # 透传嵌套孙Agent的事件（加一层前缀）
                    forwarded = dict(event)
                    forwarded["type"] = f"sub_{event_type}"
                    forwarded["depth"] = event.get("depth", depth)
                    forwarded["delegate_id"] = event.get("delegate_id", delegate_id)
                    await event_queue.put(forwarded)
        except Exception as e:
            await signal_queue.put({
                "type": "__delegate_error__",
                "delegate_id": delegate_id,
                "message": str(e),
            })
            return

        # 子引擎 token 计入主引擎
        self.total_input_tokens += sub.total_input_tokens
        self.total_output_tokens += sub.total_output_tokens
        self.total_cache_read_tokens += sub.total_cache_read_tokens
        self.total_cache_creation_tokens += sub.total_cache_creation_tokens

        await signal_queue.put({
            "type": "__delegate_done__",
            "delegate_id": delegate_id,
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
