"""平台辅助 LLM 任务：单次调用，不走 ReAct / 工具循环。

当前提供会话标题生成；后续可在此文件追加上下文压缩等同类逻辑。
调用方注入 ModelProvider（通常为辅助模型），本模块不访问 app / DB。
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from .token_utils import truncate_text
from ..prompts import TITLE_SYSTEM_PROMPT, TITLE_USER_PREFIX

if TYPE_CHECKING:
    from ..core.provider import ModelProvider

logger = logging.getLogger(__name__)

TITLE_MAX_CHARS = 50
USER_TEXT_MAX_CHARS = 2000
TITLE_MAX_TOKENS = 64
TITLE_TEMPERATURE = 0.3

_WRAP_QUOTES = "「」『』\"'“”‘’"


def _fallback_title(user_texts: list[str]) -> str:
    """用首条非空用户消息截断作为标题。"""
    for text in user_texts:
        compact = " ".join((text or "").split())
        if compact:
            return compact[:TITLE_MAX_CHARS]
    return "未命名"


def _clean_title(raw: str) -> str:
    """去掉模型输出中的引号、换行和多余空白。"""
    text = (raw or "").strip()
    if not text:
        return ""
    text = text.splitlines()[0].strip()
    text = text.strip(_WRAP_QUOTES + " \t")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:TITLE_MAX_CHARS]


def _build_title_user_prompt(user_texts: list[str]) -> str:
    parts: list[str] = []
    for i, text in enumerate(user_texts, 1):
        clipped = truncate_text(
            (text or "").strip(),
            USER_TEXT_MAX_CHARS,
            mode="chars",
            marker="…",
        )
        if not clipped:
            continue
        parts.append(f"{i}. {clipped}")
    return TITLE_USER_PREFIX + "\n".join(parts)


async def generate_session_title(
    provider: "ModelProvider",
    user_texts: list[str],
) -> str:
    """根据用户消息单次调用 LLM，生成会话标题。

    无 tools、无循环。输出为空或无法解析时回退到首条用户消息截断。
    """
    fallback = _fallback_title(user_texts)
    if not any((t or "").strip() for t in user_texts):
        return fallback
    prompt = _build_title_user_prompt(user_texts)

    messages = [{"role": "user", "content": prompt}]
    try:
        resp = await provider.chat(
            messages=provider.convert_messages(messages),
            system=TITLE_SYSTEM_PROMPT,
            tools=None,
            max_tokens=TITLE_MAX_TOKENS,
            temperature=TITLE_TEMPERATURE,
        )
    except Exception:
        logger.warning("session title LLM call failed", exc_info=True)
        raise

    cleaned = _clean_title(resp.content or "")
    return cleaned or fallback
