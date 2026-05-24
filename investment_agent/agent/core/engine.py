"""双循环执行引擎：快循环（LLM推理→工具调用→结果追加）+ 慢思考（定期全局复盘）"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import AsyncGenerator, Callable

from .models import ModelProvider, LLMResponse, ToolCall
from .tool_executor import (
    ToolExecutor, LoopDetector, create_tool_executor,
    CLONE_MIN_REMAINING, DELEGATE_MIN_REMAINING,
)
from .task_planner import TaskPlanner, extract_text_from_content
from ..config import (
    SLOW_THINK_PROMPT,
    TRUNCATION_CONTINUE_PROMPT,
)
from ..context.runtime_trimmer import RuntimeTrimmer

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
        tool_executor: ToolExecutor | None = None,
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
        self.context_trim_interval = context_trim_interval
        self.tool_trim_limits = tool_trim_limits or {}
        self._runtime_trimmer = runtime_trimmer

        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cache_read_tokens = 0
        self.total_cache_creation_tokens = 0

        # ── 子Agent配置 ──
        self.subagent_depth = subagent_depth
        self.max_subagent_depth = max_subagent_depth
        self.max_concurrent_subagents = max_concurrent_subagents
        self.sub_agent_mode = sub_agent_mode

        # ── 组合组件 ──
        self._tool_executor = tool_executor or create_tool_executor(
            sub_agent_mode, max_concurrent_subagents,
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

    @property
    def system_prompt(self) -> str:
        """动态拼接：基础 prompt + 项目路径 + 已注册 skill 的名称/描述"""
        prompt = self._system_prompt

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
            + "\n\n> 使用 Skill 工具加载技能完整说明后再执行。\n\n"
            "## 子任务委派策略\n"
            "加载技能说明后，分析其工作流程是否包含互不依赖的子阶段。若技能明确分为多个独立分析维度"
            "应使用 DelegateTask 将各维度委派给子Agent并行执行。"
            "父Agent保留全局判断（交叉验证、综合定级），子Agent返回结果后汇总整合。"
            "简单场景（如仅查单一指标）直接执行，无需委派。"
        )

    @system_prompt.setter
    def system_prompt(self, value: str) -> None:
        self._system_prompt = value

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
        loop_detector = LoopDetector(self.loop_threshold, self.LOOP_WHITELIST)
        step = 0

        while step < self.max_steps:
            # 安全检查
            stop_event = self._check_safety(step)
            if stop_event:
                yield stop_event
                return

            step += 1
            self._messages = messages
            yield {"type": "step_start", "step": step}

            # 上下文裁剪
            messages, trim_event = self._maybe_trim_context(messages, step)
            if trim_event:
                yield trim_event

            # 慢思考
            async for event in self._maybe_slow_think(messages, step):
                if event.get("_inject"):
                    messages.append(event["_inject"])
                else:
                    yield event

            # LLM 调用
            response = None
            async for event in self._call_llm(messages, step):
                if event.get("_result"):
                    response = event["_result"]
                else:
                    yield event
            if not response:
                return  # 错误事件已 yield

            # 处理 LLM 响应
            async for event in self._process_response(messages, response, step):
                if event.get("_messages"):
                    messages = event["_messages"]
                elif event.get("_terminal"):
                    yield event["_terminal"]
                    if event["_terminal"]["type"] == "done":
                        return
                    continue  # 截断恢复，继续循环
                else:
                    yield event

            if response.tool_calls:
                # 死循环检测
                if loop_detector.check(response.tool_calls):
                    yield loop_detector.error_event()
                    return

                # 工具执行
                tool_results = []
                async for event in self._tool_executor.execute(response.tool_calls, self):
                    if event.get("_internal_result"):
                        tool_results = event["_internal_result"]
                    else:
                        yield event
                messages.append({"role": "user", "content": tool_results})

        else:
            yield {"type": "error", "message": f"Max steps ({self.max_steps}) reached."}

    # ── run() 辅助方法 ────────────────────────────────────────────────

    def _check_safety(self, step: int) -> dict | None:
        """安全检查：中断 + token 预算。返回终止事件或 None。"""
        if self._interrupt.is_set():
            return {"type": "interrupted", "step": step}
        if self.total_input_tokens + self.total_output_tokens >= self.token_budget:
            return {"type": "error", "message": f"Token budget ({self.token_budget}) exceeded."}
        return None

    def _maybe_trim_context(self, messages: list[dict], step: int) -> tuple[list[dict], dict | None]:
        """每 N 步裁剪旧消息。返回 (messages, trim_event)。"""
        if (
            self._runtime_trimmer is not None
            and self.context_trim_interval > 0
            and step > 1
            and step % self.context_trim_interval == 0
        ):
            messages = self._runtime_trimmer.trim(messages, step)
            return messages, {"type": "context_trim", "step": step}
        return messages, None

    async def _maybe_slow_think(self, messages: list[dict], step: int) -> AsyncGenerator[dict, None]:
        """每 N 步触发慢思考。yield 事件 + _inject 消息。"""
        if self.slow_think_interval <= 0 or step <= 1 or step % self.slow_think_interval != 0:
            return
        reflection = await self._do_slow_think(messages, step)
        if reflection:
            yield {"type": "slow_think", "content": reflection}
            yield {"_inject": {"role": "user", "content": f"[慢思考反思 @ step {step}] {reflection}"}}

    async def _call_llm(self, messages: list[dict], step: int) -> AsyncGenerator[dict, None]:
        """调用 LLM，yield llm_request / llm_response / text_delta 事件。
        最后 yield {"_result": response} 返回 LLMResponse。
        """
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
        try:
            response: LLMResponse = await self.provider.chat(**chat_kwargs)
        except Exception as e:
            yield {"type": "error", "message": str(e)}
            return

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

        if response.content:
            yield {"type": "text_delta", "content": response.content}

        yield {"_result": response}

    async def _process_response(
        self, messages: list[dict], response: LLMResponse, step: int,
    ) -> AsyncGenerator[dict, None]:
        """处理 LLM 响应：构造 assistant 消息，处理截断或完成。

        yield 事件类型：
        - {"_messages": [...]} — 更新消息列表（工具调用场景）
        - {"_terminal": {...}} — 终止事件（done 或截断恢复后的 continue）
        - {"type": "text_delta", ...} — 截断恢复提示
        """
        if not response.tool_calls:
            # 无工具调用
            if response.stop_reason == "length":
                # 输出被截断，注入"继续"提示
                if response.content:
                    messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": TRUNCATION_CONTINUE_PROMPT})
                yield {"type": "text_delta", "content": "\n\n[输出被截断，自动请求继续...]\n\n"}
                yield {"_terminal": None}  # 非 done，continue
                return

            # 正常结束
            assistant_msg = self._build_assistant_message(response)
            messages.append(assistant_msg)
            yield {"_terminal": {
                "type": "done",
                "usage": {
                    "input_tokens": self.total_input_tokens,
                    "output_tokens": self.total_output_tokens,
                    "cache_read_tokens": self.total_cache_read_tokens,
                    "cache_creation_tokens": self.total_cache_creation_tokens,
                },
            }}
            return

        # 有工具调用 → 构造 assistant 消息
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
        yield {"_messages": messages}

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
        return prompt + " 请基于对话历史评估当前任务进展是否正常。"

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
        slim_messages = [messages[0]]
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
                "messages": self.provider._convert_messages(slim_messages),
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
            if resp.content:
                return resp.content.strip()
        except Exception:
            _log.warning("Slow think failed at step %d", step, exc_info=True)

        return None
