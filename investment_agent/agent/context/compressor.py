from __future__ import annotations

import json
import logging

from .token_utils import count_tokens, estimate_message_tokens, estimate_tokens

logger = logging.getLogger(__name__)


def _clip_text(text: str, max_chars: int) -> str:
    """截断文本到指定字符数，追加压缩标记"""
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n...[compressed]"


def compress_messages(messages: list[dict], cfg: dict | None = None) -> list[dict]:
    """上下文分级压缩：保留最近消息原文，旧消息截断，总量超预算时二次压缩

    策略：
    1. 最近 N 条消息保留原文（可读性强）
    2. 更早的消息截断至 max_chars_per_msg 字符
    3. 非文本消息（如 tool_call blocks）不压缩，避免损坏协议结构
    4. 如果总量仍超预算，从旧到新逐步压缩到最低 120 字符
    5. token 估算用于总量计量，替代纯字符计数
    """
    cfg = cfg or {}
    enabled = cfg.get("enabled", True)
    if not enabled:
        return messages

    recent_keep = max(0, int(cfg.get("recent_keep", 6)))
    max_chars_per_msg = max(200, int(cfg.get("max_chars_per_msg", 2000)))
    total_budget_chars = max(2000, int(cfg.get("total_budget_chars", 20000)))

    # 参数冲突检测：保留区不应超过总预算的 60%
    if recent_keep * max_chars_per_msg > total_budget_chars * 0.6:
        recent_keep = max(1, int(total_budget_chars * 0.6 / max_chars_per_msg))
        logger.warning(
            "Compress config conflict: recent_keep * max_chars_per_msg > 60%% of total_budget. "
            "recent_keep auto-adjusted to %d.", recent_keep
        )

    if not messages:
        return messages

    n = len(messages)
    keep_from = max(0, n - recent_keep)  # 从第几条开始保留原文

    compressed: list[dict] = []
    running_tokens = 0

    for i, msg in enumerate(messages):
        role = msg.get("role")
        content = msg.get("content", "")

        # 最近的消息保留原文不动
        if i >= keep_from:
            compressed_msg = {"role": role, "content": content}
            compressed.append(compressed_msg)
            running_tokens += estimate_message_tokens(compressed_msg)
            continue

        # 旧消息：只压缩纯文本，结构化内容（tool 调用/结果）保持不动
        if isinstance(content, str):
            clipped = _clip_text(content, max_chars_per_msg)
            compressed_msg = {"role": role, "content": clipped}
        else:
            compressed_msg = {"role": role, "content": content}

        compressed.append(compressed_msg)
        running_tokens += estimate_message_tokens(compressed_msg)

    # 用 token 估算判断是否超预算
    if running_tokens <= total_budget_chars:
        return compressed

    # 超出预算 → 对旧消息的文本内容做更激进的截断（每条约保留 120 字符底线）
    over_tokens = running_tokens - total_budget_chars
    for i in range(0, keep_from):
        msg = compressed[i]
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        if over_tokens <= 0:
            break

        min_keep = 120  # 最少保留字符，维持基本语义上下文
        if len(content) <= min_keep:
            continue

        # 逐步缩减，每次缩减后重新估算 token 节省量
        removable = len(content) - min_keep
        # 按比例估算：缩减 removable 字符预期节省多少 token
        token_density = estimate_tokens(content) / max(len(content), 1)
        savings_per_char = token_density
        cut_chars = min(removable, max(1, int(over_tokens / max(savings_per_char, 0.01))))
        new_len = max(min_keep, len(content) - cut_chars)
        msg["content"] = _clip_text(content, new_len)
        over_tokens -= int(cut_chars * savings_per_char)

    return compressed


# ── LLM summarization ───────────────────────────────────────────────

SUMMARIZE_SYSTEM_PROMPT = """You are creating a compressed summary of a financial analysis conversation.
Summarize the key findings, data points, decisions, and current task state.

Focus on:
1. Stock symbols discussed and key metrics (PE, ROE, revenue, profit, etc.)
2. Tools called and their important results (especially numbers)
3. User's stated goals, constraints, and preferences
4. Current progress and next steps
5. Any warnings, errors, or limitations encountered

Rules:
- Be concise but precise. Preserve specific numbers and findings exactly.
- Write in Chinese with English for financial terms (PE, ROE, EPS, etc.).
- Output ONLY the summary text, no preamble or meta-commentary."""


def _build_summary_user_prompt(
    messages: list[dict],
    existing_summary: str | None = None,
) -> str:
    msg_texts = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, list):
            text_parts = []
            for block in content:
                t = block.get("type", "")
                if t == "text":
                    text_parts.append(block.get("text", ""))
                elif t == "tool_use":
                    text_parts.append(
                        f"[调用工具 {block.get('name', '?')}]: {json.dumps(block.get('input', {}), ensure_ascii=False)}"
                    )
                elif t == "tool_result":
                    result = block.get("content", "")
                    if isinstance(result, str):
                        text_parts.append(f"[工具结果]: {result[:300]}")
                    else:
                        text_parts.append(f"[工具结果]: {str(result)[:300]}")
            content = "\n".join(text_parts)
        msg_texts.append(f"[{role}]: {str(content)[:500]}")

    conversation = "\n\n".join(msg_texts)

    if existing_summary:
        return (
            "Below is an existing conversation summary. Merge it with the new messages "
            "that follow to produce a single updated summary.\n\n"
            f"<existing_summary>\n{existing_summary}\n</existing_summary>\n\n"
            f"<new_messages>\n{conversation}\n</new_messages>"
        )

    return (
        "Summarize the following financial analysis conversation:\n\n"
        f"<conversation>\n{conversation}\n</conversation>"
    )


async def summarize_messages(
    provider,
    messages: list[dict],
    max_summary_tokens: int = 2000,
    existing_summary: str | None = None,
) -> str:
    """用 LLM 对一组消息做语义摘要。

    Args:
        provider: ModelProvider 实例
        messages: 待摘要的消息列表（通常为旧消息）
        max_summary_tokens: 摘要输出最大 token 数
        existing_summary: 已有摘要（增量合并模式）
    """
    if not messages:
        return existing_summary or ""

    user_prompt = _build_summary_user_prompt(messages, existing_summary)

    try:
        response = await provider.chat(
            messages=[{"role": "user", "content": user_prompt}],
            system=SUMMARIZE_SYSTEM_PROMPT,
            max_tokens=max_summary_tokens,
            temperature=0.3,
        )
        return response.content.strip()
    except Exception:
        logger.exception("Summarization LLM call failed, falling back to truncation")
        return existing_summary or "[摘要生成失败]"


def create_summary_message(summary_text: str) -> dict:
    """创建包含摘要的 user 消息（Anthropic 推荐的 <summary> 标签格式）。"""
    return {
        "role": "user",
        "content": [{"type": "text", "text": f"<summary>\n{summary_text}\n</summary>"}],
    }
