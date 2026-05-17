from __future__ import annotations

import logging

from .token_utils import estimate_message_tokens, estimate_tokens

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
