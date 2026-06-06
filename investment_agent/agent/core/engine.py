"""双循环执行引擎：快循环（LLM推理→工具调用→结果追加）+ 慢思考（定期全局复盘）"""

import asyncio
import logging
import uuid
from typing import AsyncGenerator, Callable

from ._signals import _Terminal, _Value
from ..constants import EventType, StopReason
from .provider import ModelProvider, LLMResponse, ToolCall
from .prompt_builder import PromptBuilder
from .tool_executor import ToolExecutor, LoopDetector
from .task_planner import TaskPlanner, extract_text_from_content
from .slow_think import SlowThinkStrategy
from .safety_checker import SafetyChecker
from .context_trimmer import ContextTrimmer
from ..config import (
    EngineConfig,
    TRUNCATION_CONTINUE_PROMPT,
)
from ..context.runtime_compressor import RuntimeCompressor

_log = logging.getLogger(__name__)


class AgentEngine:
    """双循环执行引擎：快循环（LLM推理→工具调用→结果追加）+ 慢思考（定期全局复盘）"""

    # ── 常量 ──
    SKILL_BODY_MAX_CHARS = 3_000      # 技能说明截断长度
    PLANNING_MAX_TOKENS = 512         # 任务指令生成 max_tokens
    SLOW_THINK_MAX_TOKENS = 200       # 慢思考 max_tokens（够用即可，过大易生成工具调用格式）
    SYSTEM_PROMPT_EXCERPT_CHARS = 200 # 慢思考 system prompt 截取长度
    REASONING_MAX_CHARS = 300         # 推理内容保留长度
    LOOP_WHITELIST = {"run_command", "DelegateTask"}  # 不受死循环检测限制的工具

    def __init__(
        self,
        session_id: str,
        config: EngineConfig,
        system_prompt: str = "",
        provider: ModelProvider | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        runtime_compressor: RuntimeCompressor | None = None,
        subagent_depth: int = 0,
    ):
        self.session_id = session_id
        self.task_id = str(uuid.uuid4())
        self._system_prompt = system_prompt
        self._prompt_builder: PromptBuilder | None = None
        self.provider = provider
        self.tools: list[dict] = []
        self.tool_handlers: dict[str, Callable] = {}
        self._skills: list = []
        self._allowed_skill_names: set[str] = set()
        self._interrupt = asyncio.Event()

        self.temperature = temperature
        self.max_tokens = max_tokens

        # 引擎参数：全部来自 config
        self.max_steps = config.max_steps
        self.slow_think_interval = config.slow_think_interval
        self.token_budget = config.token_budget
        self.loop_threshold = config.loop_detection_threshold
        self.context_trim_token_threshold = config.context_trim_token_threshold

        # 上下文卸载参数（子Agent创建时需要读取）
        self.offload_threshold = config.offload_threshold
        self.offload_summary_strategy = config.offload_summary_strategy
        self.offload_summary_chars = config.offload_summary_chars

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cache_read_tokens = 0
        self.total_cache_creation_tokens = 0
        self._last_input_tokens = 0       # 上一次 LLM 调用的 input_tokens（非累计，用于阈值判断）
        self._llm_call_count = 0       # LLM 调用次数统计
        self._tool_call_count = 0      # 工具调用次数统计
        self._start_ts = 0.0           # 会话开始时间戳

        # 慢思考缓存
        self._cached_role_system: str | None = None
        self.subagent_depth = subagent_depth
        self.max_subagent_depth = config.max_subagent_depth

        # ── 组合组件 ──
        self._tool_executor = ToolExecutor()
        self._slow_think = SlowThinkStrategy()
        self._safety = SafetyChecker()
        self._trimmer = ContextTrimmer(
            compressor=runtime_compressor,
            token_threshold=config.context_trim_token_threshold,
        )
        self.task_planner: TaskPlanner | None = None  # 延迟初始化（需要 provider）

        self._messages: list[dict] = []

    # ── 注册 / 属性 ──────────────────────────────────────────────────

    def register_tool(self, schema: dict, handler: Callable) -> None:
        """注册工具：schema 给 LLM 看，handler 执行实际逻辑"""
        self.tools.append(schema)
        self.tool_handlers[schema["name"]] = handler

    def register_skill(self, skill) -> None:
        """注册技能：记录 skill 对象，供 system_prompt property 拼接 prompt"""
        self._skills.append(skill)
        self._allowed_skill_names.add(skill.name)
        self._prompt_builder = None

    @property
    def system_prompt(self) -> str | list[dict]:
        """动态拼接：基础 prompt + 项目路径 + 已注册 skill 的名称/描述"""
        if self._prompt_builder is None:
            self._prompt_builder = PromptBuilder(self._system_prompt, self._skills)
        return self._prompt_builder.build()

    @system_prompt.setter
    def system_prompt(self, value: str) -> None:
        self._system_prompt = value
        self._prompt_builder = None

    def interrupt(self) -> None:
        """发送中断信号，优雅停止当前任务"""
        self._interrupt.set()

    def _ensure_task_planner(self) -> TaskPlanner:
        """延迟初始化 TaskPlanner（需要 provider 就绪后调用）。"""
        if self.task_planner is None and self.provider:
            self.task_planner = TaskPlanner(
                provider=self.provider,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                planning_max_tokens=self.PLANNING_MAX_TOKENS,
                skill_body_max_chars=self.SKILL_BODY_MAX_CHARS,
            )
        return self.task_planner

    # ── 主循环 ────────────────────────────────────────────────────────

    async def run(self, messages: list[dict]) -> AsyncGenerator[dict, None]:
        """主执行循环：SSE 流式产出每一步的事件。"""
        if not self.provider:
            yield {"type": EventType.ERROR, "message": "No model provider configured."}
            return

        self._ensure_task_planner()
        self._start_ts = __import__('time').monotonic()
        loop_detector = LoopDetector(
            self.loop_threshold, self.LOOP_WHITELIST
        )
        step = 0

        self._inject_date(messages)

        while step < self.max_steps:
            # ── 安全检查 ──
            safety_result = self._safety.check(self, step, messages)
            if safety_result.stop_event:
                yield safety_result.stop_event
                return

            step += 1
            self._messages = messages
            yield {"type": EventType.STEP_START, "step": step}

            # ── 上下文裁剪 ──
            messages, trim_event = await self._trimmer.maybe_trim(
                messages, step, self._last_input_tokens,
            )
            if trim_event:
                yield trim_event

            # ── 慢思考 ──
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

            # ── LLM 调用 ──
            response = None
            async for event in self._call_llm(messages, step):
                if isinstance(event, _Value):
                    response = event.value
                else:
                    yield event
            if not response:
                return

            # ── 处理响应 ──
            has_tool_calls = False
            async for event in self._process_response(messages, response, step):
                if isinstance(event, _Value):
                    has_tool_calls = event.value
                elif isinstance(event, _Terminal):
                    if event.event is not None:
                        yield event.event
                    if event.event is not None and event.event.get("type") == EventType.DONE:
                        return
                    break
                else:
                    yield event

            if has_tool_calls:
                # 记录工具调用（供慢思考策略追踪）
                self._slow_think.record_tool_result(
                    has_error=False,
                    tool_names=[tc.name for tc in response.tool_calls],
                )

                # 死循环检测
                if loop_detector.check(response.tool_calls):
                    yield loop_detector.error_event()
                    return

                # 工具执行
                self._tool_call_count += len(response.tool_calls)
                tool_results = []
                has_error = False
                async for event in self._tool_executor.execute(
                    response.tool_calls, self
                ):
                    if isinstance(event, _Value):
                        tool_results = event.value
                    else:
                        if event.get("type") == EventType.TOOL_RESULT:
                            output = str(event.get("output", ""))
                            if "error" in output.lower() or "失败" in output or "错误" in output:
                                has_error = True
                        yield event

                # 记录失败（供慢思考策略追踪）
                self._slow_think.record_tool_result(
                    has_error=has_error,
                    tool_names=[tc.name for tc in response.tool_calls],
                )

                messages.append({"role": "user", "content": tool_results})

        else:
            yield {"type": EventType.ERROR, "message": f"Max steps ({self.max_steps}) reached."}

    # ── 辅助方法 ─────────────────────────────────────────────────────

    @staticmethod
    def _inject_date(messages: list[dict]) -> None:
        """将当前日期注入到第一条消息开头（避免破坏 system prompt cache）。"""
        from datetime import datetime
        now = datetime.now()
        date_note = (
            f"[系统信息] 当前时间为 {now.year} 年 {now.month} 月 {now.day} 日 "
            f"{now.hour:02d}:{now.minute:02d}。"
            f"请以当前时间为基准判断时间相关的问题。\n\n"
        )
        msg = messages[0]
        content = msg.get("content", "")
        if isinstance(content, str):
            msg["content"] = date_note + content
        elif isinstance(content, list):
            msg["content"] = [{"type": "text", "text": date_note}] + content

    async def _call_llm(self, messages: list[dict], step: int) -> AsyncGenerator:
        """调用 LLM，yield llm_request / llm_response / text_delta 事件。"""
        yield {
            "type": EventType.LLM_REQUEST,
            "step": step,
            "messages": messages,
        }
        system = self.system_prompt
        tools = list(self.tools) if self.tools else None

        chat_kwargs: dict = {
            "messages": self.provider.convert_messages(messages),
            "system": system,
            "tools": tools,
        }
        if self.temperature is not None:
            chat_kwargs["temperature"] = self.temperature
        if self.max_tokens is not None:
            chat_kwargs["max_tokens"] = self.max_tokens
        try:
            response: LLMResponse = await self.provider.chat(**chat_kwargs)
        except Exception as e:
            yield {"type": EventType.ERROR, "message": str(e)}
            return

        self.total_input_tokens += response.input_tokens
        self.total_output_tokens += response.output_tokens
        self.total_cache_read_tokens += response.cache_read_tokens
        self.total_cache_creation_tokens += response.cache_creation_tokens
        self._last_input_tokens = response.input_tokens
        self._llm_call_count += 1

        yield {
            "type": EventType.LLM_RESPONSE,
            "step": step,
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
            "cache_read_tokens": response.cache_read_tokens,
            "cache_creation_tokens": response.cache_creation_tokens,
            "content": response.content or "",
            "reasoning": response.reasoning_content or "",
            "tool_calls": [
                {"name": tc.name, "input": tc.input}
                for tc in (response.tool_calls or [])
            ],
        }

        if response.content:
            yield {"type": EventType.TEXT_DELTA, "content": response.content}

        yield _Value(response)

    async def _process_response(
        self, messages: list[dict], response: LLMResponse, step: int,
    ) -> AsyncGenerator:
        """处理 LLM 响应：构造 assistant 消息，处理截断或完成。"""
        if not response.tool_calls:
            if response.stop_reason == StopReason.LENGTH:
                if response.content:
                    messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": TRUNCATION_CONTINUE_PROMPT})
                yield {"type": EventType.TEXT_DELTA, "content": "\n\n[输出被截断，自动请求继续...]\n\n"}
                yield _Terminal(None)
                return

            assistant_msg = self._build_assistant_message(response)
            messages.append(assistant_msg)
            yield _Terminal({
                "type": EventType.DONE,
                "usage": {
                    "input_tokens": self.total_input_tokens,
                    "output_tokens": self.total_output_tokens,
                    "cache_read_tokens": self.total_cache_read_tokens,
                    "cache_creation_tokens": self.total_cache_creation_tokens,
                },
                "stats": {
                    "llm_calls": self._llm_call_count,
                    "tool_calls": self._tool_call_count,
                    "cache_hit_ratio": round(
                        self.total_cache_read_tokens / max(self.total_input_tokens, 1) * 100, 1
                    ),
                    "avg_tokens_per_call": (
                        (self.total_input_tokens + self.total_output_tokens) // max(self._llm_call_count, 1)
                    ),
                },
            })
            return

        assistant_content = []
        if response.reasoning_content:
            assistant_content.append({
                "type": "reasoning",
                "content": self._truncate_reasoning(response.reasoning_content),
            })
        if response.extra_blocks:
            assistant_content.extend(response.extra_blocks)
        if response.content:
            assistant_content.append({"type": "text", "text": response.content})
        for tc in response.tool_calls:
            assistant_content.append({
                "type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.input,
            })
        messages.append({"role": "assistant", "content": assistant_content})
        yield _Value(True)

    def _build_assistant_message(self, response: LLMResponse) -> dict:
        """构造 assistant 消息（兼容 Anthropic content block 格式）。"""
        if response.reasoning_content or response.extra_blocks:
            blocks = []
            if response.reasoning_content:
                blocks.append({
                    "type": "reasoning",
                    "content": self._truncate_reasoning(response.reasoning_content),
                })
            blocks.extend(response.extra_blocks)
            if response.content:
                blocks.append({"type": "text", "text": response.content})
            return {"role": "assistant", "content": blocks}
        return {"role": "assistant", "content": response.content}

    # ── 工具方法 ─────────────────────────────────────────────────────

    @staticmethod
    def _extract_text_from_content(content) -> str:
        return extract_text_from_content(content)

    def _extract_role_from_system(self) -> str:
        """从 system_prompt 中提取角色定义（第一段），用于慢思考的精简 system。"""
        if self._cached_role_system is not None:
            return self._cached_role_system

        prompt = self.system_prompt or ""
        if isinstance(prompt, list):
            for block in prompt:
                if isinstance(block, dict) and block.get("type") == "text":
                    prompt = block.get("text", "")
                    break
            else:
                return "请基于对话历史评估当前任务进展是否正常。"

        for marker in ("\n\n", "\n##", "\n# "):
            idx = prompt.find(marker)
            if idx != -1:
                prompt = prompt[:idx]
                break

        prompt = prompt.strip()
        max_chars = self.SYSTEM_PROMPT_EXCERPT_CHARS
        if len(prompt) > max_chars:
            prompt = prompt[:max_chars].rsplit("。", 1)[0] + "。"
        result = prompt + " 请基于对话历史评估当前任务进展是否正常。"
        self._cached_role_system = result
        return result

    def _truncate_reasoning(self, content: str, max_chars: int | None = None) -> str:
        """截断推理内容：短于 max_chars 完整保留，否则保留首尾各一半。"""
        if max_chars is None:
            max_chars = self.REASONING_MAX_CHARS
        if len(content) <= max_chars:
            return content
        half = max_chars // 2
        return content[:half] + "\n...[推理已截断]...\n" + content[-half:]
