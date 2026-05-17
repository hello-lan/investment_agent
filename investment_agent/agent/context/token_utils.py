from __future__ import annotations

import re


def estimate_tokens(text: str) -> int:
    """中英文自适应 token 估算。

    英文 ~4 char/token，中文 ~2.0 char/token。
    混合文本按字符类型比例加权估算，结果偏保守（略高估）。
    """
    if not text:
        return 0

    total = len(text)
    cjk = len(re.findall(r'[一-鿿㐀-䶿豈-﫿]', text))
    latin = total - cjk

    return int(latin / 4.0 + cjk / 2.0)


def estimate_message_tokens(message: dict) -> int:
    """估算单条消息的 token 数，支持 str 和 list[dict] content 格式。"""
    content = message.get("content", "")
    if isinstance(content, str):
        return estimate_tokens(content)
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, dict):
                text = block.get("text") or block.get("content") or ""
                total += estimate_tokens(str(text))
            else:
                total += estimate_tokens(str(block))
        return total
    return 0
