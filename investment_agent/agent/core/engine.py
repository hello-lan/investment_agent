"""双循环执行引擎：快循环（LLM推理→工具调用→结果追加）+ 慢思考（定期全局复盘）"""

import asyncio
import logging
import uuid
from typing import AsyncGenerator, Callable

from ._signals import _Inject, _Terminal, _Value
from .provider import ModelProvider, LLMResponse, ToolCall
from .prompt_builder import PromptBuilder
from .tool_executor import ToolExecutor, LoopDetector
from .task_planner import TaskPlanner, extract_text_from_content
from ..config import (
    EngineConfig,
    SLOW_THINK_PROMPT,
    TRUNCATION_CONTINUE_PROMPT,
)
from ..context.runtime_compressor import RuntimeCompressor

_log = logging.getLogger(__name__)


class AgentEngine:
    """双循环执行引擎：快循环（LLM推理→工具调用→结果追加）+ 慢思考（定期全局复盘）"""

    # ── 常量 ──
    SKILL_BODY_MAX_CHARS = 3_000      # 技能说明截断长度
    PLANNING_MAX_TOKENS = 512         # 任务指令生成 max_tokens
    SLOW_THINK_MAX_TOKENS = 512       # 慢思考 max_tokens
    SYSTEM_PROMPT_EXCERPT_CHARS = 200 # 慢思考 system prompt 截取长度
    REASONING_MAX_CHARS = 300         # 推理内容保留长度
    LOOP_WHITELIST = {"run_command", "DelegateTask"}  # 不受死循环检测限制的工具
    SLOW_THINK_MAX_INTERVAL = 8       # 慢思考最大间隔（保底触发）

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
        self.run_command_limit = config.run_command_limit
        self.context_trim_interval = config.context_trim_interval
        self.tool_trim_limits = config.tool_trim_limits
        self._runtime_compressor = runtime_compressor

        # 上下文卸载参数（子Agent创建时需要读取）
        self.offload_threshold = config.offload_threshold
        self.offload_summary_strategy = config.offload_summary_strategy
        self.offload_summary_chars = config.offload_summary_chars

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cache_read_tokens = 0
        self.total_cache_creation_tokens = 0
        self._llm_call_count = 0       # LLM 调用次数统计
        self._tool_call_count = 0      # 工具调用次数统计
        self._start_ts = 0.0           # 会话开始时间戳

        # 慢思考缓存
        self._cached_role_system: str | None = None
        self.subagent_depth = subagent_depth
        self.max_subagent_depth = config.max_subagent_depth

        # 自适应慢思考触发器状态
        self._consecutive_failures = 0
        self._slow_think_tool_switches = 0
        self._last_tool: str | None = None
        self._last_slow_think_step = 0

        # ── 组合组件 ──
        self._tool_executor = ToolExecutor()
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
        self._prompt_builder = None  # 技能变更，下次访问时重建

    @property
    def system_prompt(self) -> str | list[dict]:
        """动态拼接：基础 prompt + 项目路径 + 已注册 skill 的名称/描述"""
        if self._prompt_builder is None:
            self._prompt_builder = PromptBuilder(self._system_prompt, self._skills)
        return self._prompt_builder.build()

    @system_prompt.setter
    def system_prompt(self, value: str) -> None:
        self._system_prompt = value
        self._prompt_builder = None  # 基础 prompt 变更，下次访问时重建

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
        """主执行循环：SSE 流式产出每一步的事件"""
        if not self.provider:
            yield {"type": "error", "message": "No model provider configured."}
            return

        self._ensure_task_planner()
        self._start_ts = __import__('time').monotonic()
        loop_detector = LoopDetector(self.loop_threshold, self.LOOP_WHITELIST, self.run_command_limit)
        step = 0

        # 注入当前日期到首条消息（不在 system prompt 中注入以保持 cache 命中）
        self._inject_date(messages)

        while step < self.max_steps:
            # 安全检查
            stop_event = self._check_safety(step)
            if stop_event:
                yield stop_event
                return

            # 步数预算预警
            self._check_step_budget(step, messages)

            step += 1
            self._messages = messages
            yield {"type": "step_start", "step": step}

            # 上下文裁剪
            messages, trim_event = await self._maybe_trim_context(messages, step)
            if trim_event:
                yield trim_event

            # 慢思考
            async for event in self._maybe_slow_think(messages, step):
                if isinstance(event, _Inject):
                    messages.append(event.message)
                else:
                    yield event

            # LLM 调用
            response = None
            async for event in self._call_llm(messages, step):
                if isinstance(event, _Value):
                    response = event.value
                else:
                    yield event
            if not response:
                return  # 错误事件已 yield

            # 处理 LLM 响应
            has_tool_calls = False
            async for event in self._process_response(messages, response, step):
                if isinstance(event, _Value):
                    has_tool_calls = event.value
                elif isinstance(event, _Terminal):
                    if event.event is not None:
                        yield event.event
                    if event.event is not None and event.event.get("type") == "done":
                        return
                    # event.event is None → 截断恢复，继续循环
                    break
                else:
                    yield event

            if has_tool_calls:
                # 自适应慢思考：追踪工具切换
                for tc in response.tool_calls:
                    if tc.name != self._last_tool:
                        if self._last_tool is not None:
                            self._slow_think_tool_switches += 1
                        self._last_tool = tc.name

                # 死循环检测
                if loop_detector.check(response.tool_calls):
                    yield loop_detector.error_event()
                    return

                # 工具执行
                self._tool_call_count += len(response.tool_calls)
                tool_results = []
                has_error = False
                async for event in self._tool_executor.execute(response.tool_calls, self):
                    if isinstance(event, _Value):
                        tool_results = event.value
                    else:
                        if event.get("type") == "tool_result":
                            output = str(event.get("output", ""))
                            if "error" in output.lower() or "失败" in output or "错误" in output:
                                has_error = True
                        yield event

                # 自适应慢思考：追踪失败
                if has_error:
                    self._consecutive_failures += 1
                else:
                    self._consecutive_failures = 0

                messages.append({"role": "user", "content": tool_results})

        else:
            yield {"type": "error", "message": f"Max steps ({self.max_steps}) reached."}

    # ── run() 辅助方法 ────────────────────────────────────────────────

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

    def _check_safety(self, step: int) -> dict | None:
        """安全检查：中断 + token 预算 + 步数预算警告。返回终止事件或 None。"""
        if self._interrupt.is_set():
            return {"type": "interrupted", "step": step}
        if self.total_input_tokens + self.total_output_tokens >= self.token_budget:
            return {"type": "error", "message": f"Token budget ({self.token_budget}) exceeded."}
        return None

    def _check_step_budget(self, step: int, messages: list[dict]) -> bool:
        """步数预算预警：剩余步数不足时注入提醒。返回 True 表示已注入。"""
        remaining = self.max_steps - step
        warn_threshold = max(5, int(self.max_steps * 0.25))  # 25% 或至少5步
        if remaining <= warn_threshold:
            # 仅在最近未注入过时注入（避免连续注入）
            last_msg = messages[-1] if messages else {}
            last_content = last_msg.get("content", "")
            if isinstance(last_content, str) and "步数预算警告" in last_content:
                return True  # 已注入过，跳过
            warning = (
                f"[步数预算警告] 剩余步数: {remaining}/{self.max_steps}。"
                f"请评估当前进度：如果仍在数据准备阶段，考虑跳过中间步骤，"
                f"直接使用已有数据快速进入核心分析。优先委派而非亲自调试。"
            )
            messages.append({"role": "user", "content": warning})
            return True
        return False

    async def _maybe_trim_context(self, messages: list[dict], step: int) -> tuple[list[dict], dict | None]:
        """每 N 步裁剪旧消息。返回 (messages, trim_event)。
        NoOpRuntimeCompressor（strategy="off"）时不 emit 事件，避免误导性日志。
        """
        from ..context.runtime_compressor import NoOpRuntimeCompressor
        if (
            self._runtime_compressor is not None
            and not isinstance(self._runtime_compressor, NoOpRuntimeCompressor)
            and self.context_trim_interval > 0
            and step > 1
            and step % self.context_trim_interval == 0
        ):
            messages = await self._runtime_compressor.compress(messages, step)
            return messages, {"type": "context_trim", "step": step}
        return messages, None

    async def _maybe_slow_think(self, messages: list[dict], step: int) -> AsyncGenerator:
        """自适应慢思考：基于信号触发而非固定间隔。

        触发条件（优先级从高到低）：
        0. 步数预算不足（≤25% 剩余）→ 强制策略调整
        1. 工具连续失败 ≥2 次 → 需要重新规划
        2. 最近 5 步频繁切换工具（≥3 种不同工具）→ 策略不稳定
        3. 距上次反思超过 SLOW_THINK_MAX_INTERVAL 步 → 保底触发
        """
        trigger_reason = ""

        # 条件 0: 步数预算不足
        remaining = self.max_steps - step
        step_warn_threshold = max(3, int(self.max_steps * 0.25))
        if remaining <= step_warn_threshold:
            trigger_reason = f"步数预算不足（剩余 {remaining}/{self.max_steps}），需要调整策略"

        # 条件 1: 连续失败
        if not trigger_reason and self._consecutive_failures >= 2:
            trigger_reason = "工具连续失败，需要重新规划"

        # 条件 2: 频繁切换工具
        if not trigger_reason and self._slow_think_tool_switches >= 3:
            trigger_reason = "策略不稳定，频繁切换工具"

        # 条件 3: 保底触发
        steps_since = step - self._last_slow_think_step
        if not trigger_reason and steps_since >= self.SLOW_THINK_MAX_INTERVAL:
            trigger_reason = f"距上次反思已 {steps_since} 步"

        # 传统 fixed-interval 也保留作为额外触发（向后兼容）
        if not trigger_reason and self.slow_think_interval > 0 and step > 1:
            if step % self.slow_think_interval == 0:
                trigger_reason = f"定时反思 @ step {step}"

        if not trigger_reason:
            return

        reflection = await self._do_slow_think(messages, step)
        if reflection:
            self._last_slow_think_step = step
            self._slow_think_tool_switches = 0  # 反思后重置切换计数
            yield {"type": "slow_think", "content": reflection, "trigger": trigger_reason}
            yield _Inject({"role": "user", "content": f"[慢思考反思 @ step {step}] {reflection}"})

    async def _call_llm(self, messages: list[dict], step: int) -> AsyncGenerator:
        """调用 LLM，yield llm_request / llm_response / text_delta 事件。
        最后 yield _Value(response) 返回 LLMResponse。
        """
        yield {
            "type": "llm_request",
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
            yield {"type": "error", "message": str(e)}
            return

        self.total_input_tokens += response.input_tokens
        self.total_output_tokens += response.output_tokens
        self.total_cache_read_tokens += response.cache_read_tokens
        self.total_cache_creation_tokens += response.cache_creation_tokens
        self._llm_call_count += 1

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

        if response.content:
            yield {"type": "text_delta", "content": response.content}

        yield _Value(response)

    async def _process_response(
        self, messages: list[dict], response: LLMResponse, step: int,
    ) -> AsyncGenerator:
        """处理 LLM 响应：构造 assistant 消息，处理截断或完成。

        yield 信号类型：
        - _Value(bool) — 是否有工具调用（消息已就地修改）
        - _Terminal(event) — 终止事件（done）或截断恢复（event=None）
        - dict — 公共事件（截断恢复提示 text_delta）
        """
        if not response.tool_calls:
            # 无工具调用
            if response.stop_reason == "length":
                # 输出被截断，注入"继续"提示
                if response.content:
                    messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": TRUNCATION_CONTINUE_PROMPT})
                yield {"type": "text_delta", "content": "\n\n[输出被截断，自动请求继续...]\n\n"}
                yield _Terminal(None)  # 非 done，continue
                return

            # 正常结束
            assistant_msg = self._build_assistant_message(response)
            messages.append(assistant_msg)
            yield _Terminal({
                "type": "done",
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

        # 有工具调用 → 构造 assistant 消息（就地修改 messages）
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
        yield _Value(True)  # 有工具调用

    def _build_assistant_message(self, response: LLMResponse) -> dict:
        """构造 assistant 消息（兼容 Anthropic content block 格式）。"""
        if response.reasoning_content or response.extra_blocks:
            blocks = []
            if response.reasoning_content:
                blocks.append({"type": "reasoning", "content": self._truncate_reasoning(response.reasoning_content)})
            blocks.extend(response.extra_blocks)
            if response.content:
                blocks.append({"type": "text", "text": response.content})
            return {"role": "assistant", "content": blocks}
        return {"role": "assistant", "content": response.content}

    # ── 工具方法 ──────────────────────────────────────────────────────

    @staticmethod
    def _extract_text_from_content(content) -> str:
        """从 Anthropic content blocks 中提取纯文本。"""
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

    async def _do_slow_think(self, messages: list[dict], step: int) -> str | None:
        """慢思考：仅发送最近消息 + 精简 system prompt，检查是否跑偏。"""
        slim_messages = [self._ensure_cache_on_first_message(messages[0])]
        assistant_positions = [
            i for i, m in enumerate(messages) if m.get("role") == "assistant"
        ]
        keep_from = assistant_positions[-(5)] if len(assistant_positions) >= 5 else (
            assistant_positions[0] if assistant_positions else 0
        )
        slim_messages.extend(messages[keep_from:])

        prompt = SLOW_THINK_PROMPT.format(step=step)
        slim_messages.append({"role": "user", "content": prompt})

        minimal_system = self._extract_role_from_system()

        try:
            think_kwargs: dict = {
                "messages": self.provider.convert_messages(slim_messages),
                "system": minimal_system,
            }
            if self.temperature is not None:
                think_kwargs["temperature"] = self.temperature
            if self.max_tokens is not None:
                think_kwargs["max_tokens"] = min(self.max_tokens, self.SLOW_THINK_MAX_TOKENS)
            else:
                think_kwargs["max_tokens"] = self.SLOW_THINK_MAX_TOKENS
            resp = await self.provider.chat(**think_kwargs)
            self.total_input_tokens += resp.input_tokens
            self.total_output_tokens += resp.output_tokens
            self.total_cache_read_tokens += resp.cache_read_tokens
            self.total_cache_creation_tokens += resp.cache_creation_tokens
            if resp.content:
                return resp.content.strip()
        except Exception:
            _log.warning("Slow think failed at step %d", step, exc_info=True)

        return None

    @staticmethod
    def _ensure_cache_on_first_message(msg: dict) -> dict:
        """给消息添加 cache_control 标记（用于慢思考等场景）。"""
        content = msg.get("content", "")
        if isinstance(content, str):
            return {
                "role": msg["role"],
                "content": [
                    {"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}
                ],
            }
        if isinstance(content, list) and content:
            content[0] = {**content[0], "cache_control": {"type": "ephemeral"}}
        return msg
