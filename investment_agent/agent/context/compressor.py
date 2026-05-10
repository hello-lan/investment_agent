from __future__ import annotations


def _clip_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}\n...[compressed]"


def compress_messages(messages: list[dict], cfg: dict | None = None) -> list[dict]:
    cfg = cfg or {}
    enabled = cfg.get("enabled", True)
    if not enabled:
        return messages

    recent_keep = max(0, int(cfg.get("recent_keep", 6)))
    max_chars_per_msg = max(200, int(cfg.get("max_chars_per_msg", 2000)))
    total_budget_chars = max(2000, int(cfg.get("total_budget_chars", 20000)))

    if not messages:
        return messages

    n = len(messages)
    keep_from = max(0, n - recent_keep)

    compressed: list[dict] = []
    running_chars = 0

    for i, msg in enumerate(messages):
        role = msg.get("role")
        content = msg.get("content", "")

        # Keep the most recent messages verbatim.
        if i >= keep_from:
            compressed_msg = {"role": role, "content": content}
            compressed.append(compressed_msg)
            running_chars += len(str(content))
            continue

        # For older content, only compress plain text messages.
        if isinstance(content, str):
            clipped = _clip_text(content, max_chars_per_msg)
            compressed_msg = {"role": role, "content": clipped}
        else:
            # Keep non-string structured messages as-is to avoid breaking tool-call transcripts.
            compressed_msg = {"role": role, "content": content}

        compressed.append(compressed_msg)
        running_chars += len(str(compressed_msg.get("content", "")))

    if running_chars <= total_budget_chars:
        return compressed

    # If still above budget, trim older text messages more aggressively.
    over_budget = running_chars - total_budget_chars
    for i in range(0, keep_from):
        msg = compressed[i]
        content = msg.get("content", "")
        if not isinstance(content, str):
            continue
        if over_budget <= 0:
            break

        # Minimum preserved prefix to keep topic context.
        min_keep = 120
        if len(content) <= min_keep:
            continue

        removable = len(content) - min_keep
        cut = min(removable, over_budget)
        new_len = len(content) - cut
        msg["content"] = _clip_text(content, new_len)
        over_budget -= cut

    return compressed
