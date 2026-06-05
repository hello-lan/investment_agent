from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .compressor import create_summary_message, summarize_messages
from .token_utils import (
    count_message_tokens,
    count_system_tokens,
    count_tokens,
    count_tool_tokens,
    get_model_context_limit,
    truncate_text,
)

from ..constants import ProviderType
from .cache_strategy import get_cache_strategy

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_MAX = 40_000
DEFAULT_TOOLS_MAX = 20_000
DEFAULT_RECENT_KEEP = 15
DEFAULT_SAFETY_MARGIN = 0.10
DEFAULT_MAX_CHARS_PER_MSG = 2000


@dataclass
class ContextResult:
    system_prompt: str | list[dict]  # list 用于 Anthropic cache_control 格式
    tools: list[dict]
    messages: list[dict]
    system_tokens: int
    tools_tokens: int
    messages_tokens: int
    total_tokens: int
    model_max_tokens: int
    warnings: list[str] = field(default_factory=list)
    did_summarize: bool = False
    new_summary: str | None = None
    summary_tokens: int = 0


class ContextManager:
    """结构化上下文预算管理 — Head-Body-Tail 模式。

    Head (system + tools) 稳定可缓存，Body (旧消息摘要) 低频变更，
    Tail (最近消息) 原始保留。pre-flight 检查确保总 token 不超模型窗口。
    """

    def __init__(self, config: dict | None = None, provider_type: str = ProviderType.ANTHROPIC,
                 model_name: str | None = None):
        cfg = config or {}
        self.enabled = cfg.get("enabled", True)
        self.provider_type = provider_type
        self.model_name = model_name or "unknown"
        self.model_max = self._resolve_model_max(cfg.get("model_max_tokens"))

        budget = cfg.get("budget", {})
        self.system_max = int(budget.get("system_max_tokens", DEFAULT_SYSTEM_MAX))
        self.tools_max = int(budget.get("tools_max_tokens", DEFAULT_TOOLS_MAX))
        self.messages_max = budget.get("messages_max_tokens")

        self.recent_keep = max(0, int(cfg.get("recent_keep", DEFAULT_RECENT_KEEP)))
        self.safety_margin = float(cfg.get("safety_margin", DEFAULT_SAFETY_MARGIN))
        self.max_chars_per_msg = int(cfg.get("max_chars_per_msg", DEFAULT_MAX_CHARS_PER_MSG))

        # summarization & caching — Phase 3/4 启用
        summ = cfg.get("summarization", {})
        self.summarization_enabled = summ.get("enabled", False)
        self.summarization_max_tokens = int(summ.get("max_summary_tokens", 2000))
        self.summarization_trigger = int(summ.get("trigger_after_messages", 25))

        caching = cfg.get("caching", {})
        self.caching_enabled = caching.get("enabled", False)

    # ── Main API ────────────────────────────────────────────────────

    async def prepare(
        self, system_prompt: str, tools: list[dict],
        messages: list[dict], *, provider=None,
        existing_summary: str | None = None,
    ) -> ContextResult:
        """处理上下文预算，返回可直接供 engine.run() 使用的 ContextResult。

        provider 为可选的 LLM 提供者，仅当 summarization.enabled 时需要。
        existing_summary 为已有摘要，用于增量合并（Phase 5）。
        """
        warnings: list[str] = []
        did_summarize = False
        new_summary: str | None = None
        summary_tokens = 0

        if not self.enabled:
            sys_tok = count_system_tokens(system_prompt)
            tools_tok = count_tool_tokens(tools)
            msg_tok = sum(count_message_tokens(m, self.provider_type) for m in messages)
            return ContextResult(
                system_prompt=system_prompt, tools=tools, messages=messages,
                system_tokens=sys_tok, tools_tokens=tools_tok,
                messages_tokens=msg_tok, total_tokens=sys_tok + tools_tok + msg_tok,
                model_max_tokens=self.model_max, warnings=warnings,
            )

        # 1. system prompt budget
        sys_prompt, sys_tokens, sys_warn = self._fit_system(system_prompt)
        if sys_warn:
            warnings.append(sys_warn)

        # 2. tools budget
        kept_tools, tools_tokens, tools_warn = self._fit_tools(tools)
        if tools_warn:
            warnings.append(tools_warn)

        # 3. message budget = remaining after system + tools + safety
        safety = int(self.model_max * self.safety_margin)
        msg_budget = self.model_max - sys_tokens - tools_tokens - safety
        if self.messages_max is not None:
            msg_budget = min(msg_budget, int(self.messages_max))

        # 4. split old / recent
        split = max(0, len(messages) - self.recent_keep)
        old_messages = messages[:split]
        recent_messages = messages[split:]

        # 5. summarization or truncation for old messages
        summary_msg = None
        if (
            self.summarization_enabled
            and provider is not None
            and len(messages) > self.summarization_trigger
            and old_messages
        ):
            # Phase 3: LLM 摘要（含 Phase 5 增量合并）
            summary_text = await summarize_messages(
                provider, old_messages,
                max_summary_tokens=self.summarization_max_tokens,
                existing_summary=existing_summary,
            )
            if summary_text:
                summary_msg = create_summary_message(summary_text)
                summary_tokens = count_message_tokens(summary_msg, self.provider_type)
                did_summarize = True
                new_summary = summary_text

        # 6. build final message list
        if summary_msg:
            recent_budget = msg_budget - summary_tokens
            recent_fit, _, _ = self._fit_messages(recent_messages, max(0, recent_budget))
            final_messages = [summary_msg] + recent_fit
        else:
            final_messages, _, msg_warn = self._fit_messages(messages, msg_budget)
            if msg_warn:
                warnings.append(msg_warn)

        msg_tokens = sum(count_message_tokens(m, self.provider_type) for m in final_messages)
        total = sys_tokens + tools_tokens + msg_tokens

        # 7. pre-flight check
        if total > self.model_max:
            logger.warning("Context overflow %d/%d — emergency trim", total, self.model_max)
            final_messages = self._emergency_trim(final_messages, total - self.model_max)
            msg_tokens = sum(count_message_tokens(m, self.provider_type) for m in final_messages)
            total = sys_tokens + tools_tokens + msg_tokens
            warnings.append("emergency_trim")

        # 8. cache structure (Phase 4)
        if self.caching_enabled and self.provider_type == ProviderType.ANTHROPIC:
            strategy = get_cache_strategy(self.provider_type)
            sys_prompt, final_messages, cached = strategy.apply_to_messages(
                sys_prompt, final_messages
            )
            if cached:
                logger.debug("Cache markers applied: system=%d tokens, messages=%d",
                           sys_tokens, msg_tokens)

        return ContextResult(
            system_prompt=sys_prompt, tools=kept_tools, messages=final_messages,
            system_tokens=sys_tokens, tools_tokens=tools_tokens,
            messages_tokens=msg_tokens, total_tokens=total,
            model_max_tokens=self.model_max, warnings=warnings,
            did_summarize=did_summarize, new_summary=new_summary,
            summary_tokens=summary_tokens,
        )

    # ── Budget fitting ──────────────────────────────────────────────

    def _fit_system(self, prompt: str) -> tuple[str, int, str | None]:
        tokens = count_system_tokens(prompt)
        if tokens <= self.system_max:
            return prompt, tokens, None
        trimmed = self._trim_system(prompt, self.system_max)
        return trimmed, count_system_tokens(trimmed), "system_prompt_trimmed"

    def _fit_tools(self, tools: list[dict]) -> tuple[list[dict], int, str | None]:
        tokens = count_tool_tokens(tools)
        if tokens <= self.tools_max:
            return list(tools), tokens, None
        # 按风险等级升序，L0 只读工具优先保留，高风险的先剔除
        sorted_tools = sorted(tools, key=lambda t: t.get("risk_level", 0))
        kept, total = [], 0
        for t in sorted_tools:
            tt = count_tool_tokens([t])
            if total + tt <= self.tools_max:
                kept.append(t)
                total += tt
        return kept, total, "tools_reduced" if len(kept) < len(tools) else None

    def _fit_messages(self, messages: list[dict], budget: int) -> tuple[list[dict], int, str | None]:
        """从最新消息开始填充预算，优先保留最近的上下文。

        逐条从最新向旧遍历：能放入的直接放入，放不下的文本消息尝试截断。
        不因单条大消息丢弃后续的小消息（无 break）。
        """
        result = []
        total = 0
        for msg in reversed(messages):
            t = count_message_tokens(msg, self.provider_type)
            if total + t <= budget:
                result.insert(0, msg)
                total += t
            else:
                content = msg.get("content", "")
                if isinstance(content, str):
                    trimmed = self._truncate_text(content, budget - total)
                    if trimmed:
                        result.insert(0, {"role": msg["role"], "content": trimmed})
                        total += count_tokens(trimmed) + 4

        warning = "messages_trimmed" if len(result) < len(messages) else None
        return result, sum(count_message_tokens(m, self.provider_type) for m in result), warning

    # ── Trimming helpers ────────────────────────────────────────────

    def _trim_system(self, prompt: str, max_tokens: int) -> str:
        """裁剪 system prompt 中的技能正文部分。"""
        marker = "# 可用技能"
        idx = prompt.find(marker)
        if idx == -1:
            return self._truncate_text(prompt, max_tokens)

        base = prompt[:idx].rstrip()
        skills = prompt[idx:]
        base_tokens = count_system_tokens(base)
        remaining = max_tokens - base_tokens
        if remaining <= 0:
            return base

        # 按技能分节，比例裁剪
        sections = skills.split("\n\n---\n\n")
        if len(sections) <= 1:
            return base + "\n\n" + self._truncate_text(sections[0], remaining)

        # 分离 header/body
        parsed = []
        for sec in sections:
            lines = sec.strip().split("\n")
            body_start = 0
            for i, ln in enumerate(lines):
                if not ln.startswith("## ") and not ln.startswith("目录:"):
                    body_start = i
                    break
            header = "\n".join(lines[:body_start]) if body_start else ""
            body = "\n".join(lines[body_start:])
            parsed.append((header, body, count_tokens(header), count_tokens(body)))

        total_header = sum(p[2] for p in parsed)
        total_body = sum(p[3] for p in parsed)
        avail = remaining - total_header

        if avail >= total_body:
            return prompt  # fits

        if avail <= 0:
            return base + "\n\n" + "\n\n---\n\n".join(
                h + "\n...[技能正文已压缩]" for h, _, _, _ in parsed
            )

        ratio = avail / total_body
        parts = []
        for header, body, _, _ in parsed:
            limit = max(40, int(count_tokens(body) * ratio))
            parts.append(header + "\n" + self._truncate_text(body, limit) if header else
                         self._truncate_text(body, limit))
        return base + "\n\n" + "\n\n---\n\n".join(parts)

    def _truncate_text(self, text: str, max_tokens: int) -> str:
        return truncate_text(text, max_tokens, mode="tokens")

    def _emergency_trim(self, messages: list[dict], excess: int) -> list[dict]:
        """pre-flight 失败时的紧急裁剪：从头部开始缩减。"""
        remaining = excess
        result = list(messages)
        i = 0
        while i < len(result) and remaining > 0:
            msg = result[i]
            content = msg.get("content", "")
            if isinstance(content, str) and len(content) > 120:
                old_tokens = count_message_tokens(msg, self.provider_type)
                target = max(30, old_tokens - remaining)
                new_text = self._truncate_text(content, target)
                result[i] = {"role": msg["role"], "content": new_text}
                remaining -= old_tokens - count_message_tokens(result[i], self.provider_type)
            i += 1
        return result

    # ── Internal helpers ────────────────────────────────────────────

    def _resolve_model_max(self, explicit: int | None) -> int:
        if explicit is not None:
            return explicit
        return get_model_context_limit(self.model_name)
