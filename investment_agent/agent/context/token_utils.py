from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# ── tiktoken lazy init ──────────────────────────────────────────────
_tokenizer = None
_tokenizer_init_attempted = False
TOKENIZER_NAME = "o200k_base"


def _get_tokenizer():
    global _tokenizer, _tokenizer_init_attempted
    if not _tokenizer_init_attempted:
        _tokenizer_init_attempted = True
        try:
            import tiktoken

            _tokenizer = tiktoken.get_encoding(TOKENIZER_NAME)
        except Exception:
            logger.debug("tiktoken unavailable, falling back to heuristic token estimator")
    return _tokenizer


# ── Heuristic estimator (fallback & backward compat) ────────────────


def estimate_tokens(text: str) -> int:
    """中英文自适应 token 估算（tiktoken 不可用时的回退方案）。

    英文 ~4 char/token，中文 ~2.0 char/token。
    """
    if not text:
        return 0
    total = len(text)
    cjk = len(re.findall(r'[一-鿿㐀-䶿豈-﫿]', text))
    latin = total - cjk
    return int(latin / 4.0 + cjk / 2.0)


# ── Real token counting ─────────────────────────────────────────────

# Message formatting overhead in tokens (Anthropic API overhead)
_ROLE_OVERHEAD = 4
_SYSTEM_OVERHEAD = 8
_TOOL_DEF_OVERHEAD = 8



def count_tokens(text: str) -> int:
    """真实 token 计数：优先 tiktoken，不可用时间退到启发式估计。

    返回 token 数，保证 >= 0。
    """
    if not text:
        return 0
    tok = _get_tokenizer()
    if tok is not None:
        try:
            return len(tok.encode(text))
        except Exception:
            logger.debug("tiktoken encode failed, falling back", exc_info=True)
    return estimate_tokens(text)


def count_message_tokens(message: dict, provider_type: str = "anthropic") -> int:
    """计算单条消息的 token 开销，含 role 标记和内容。

    provider_type 影响内容格式解析 ("anthropic" 或 "openai")。
    """
    tokens = _ROLE_OVERHEAD
    content = message.get("content", "")

    if isinstance(content, str):
        tokens += count_tokens(content)
    elif isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                tokens += count_tokens(str(block))
                continue
            block_type = block.get("type", "")
            if block_type == "text":
                tokens += count_tokens(block.get("text", ""))
            elif block_type == "tool_use":
                tokens += count_tokens(json.dumps(block, ensure_ascii=False))
            elif block_type == "tool_result":
                tokens += count_tokens(json.dumps(block, ensure_ascii=False))
            elif block_type == "reasoning":
                tokens += count_tokens(block.get("text", "") or block.get("content", ""))
            elif block_type == "tool_calls":
                tokens += count_tokens(json.dumps(block, ensure_ascii=False))
            else:
                text = block.get("text") or block.get("content") or ""
                tokens += count_tokens(str(text))
    return tokens


def count_tool_tokens(tools: list[dict]) -> int:
    """计算工具 schema 列表的总 token 开销。

    每个工具计入定义开销（~8 token）+ schema JSON 内容。
    """
    total = 0
    for tool in tools:
        total += _TOOL_DEF_OVERHEAD
        total += count_tokens(json.dumps(tool, ensure_ascii=False))
    return total


def count_system_tokens(system_prompt: str) -> int:
    """计算系统提示词的 token 开销（含系统角色包装）。"""
    if not system_prompt:
        return 0
    return _SYSTEM_OVERHEAD + count_tokens(system_prompt)


_DEFAULT_CONTEXT_LIMIT = 128_000


def get_model_context_limit(model_name: str | None) -> int:
    """获取已知模型的上下文窗口大小（token 数）。

    未知模型返回默认 128k 并记录 warning。
    """
    if not model_name:
        return _DEFAULT_CONTEXT_LIMIT

    name_lower = model_name.lower()
    if "claude" in name_lower:
        return 200_000
    if name_lower == "gpt-4":
        return 8_192
    if "gpt-4" in name_lower:
        return 128_000
    if "gpt-3.5" in name_lower:
        return 16_384

    logger.warning("Unknown model %r — assuming %d context limit", model_name, _DEFAULT_CONTEXT_LIMIT)
    return _DEFAULT_CONTEXT_LIMIT


# ── Unified text truncation ───────────────────────────────────────────


def truncate_text(
    text: str,
    limit: int,
    mode: str = "chars",
    marker: str = "...[compressed]",
) -> str:
    """统一文本截断：支持按字符或按 token 截断。

    Args:
        text: 待截断文本
        limit: 截断上限（字符数或 token 数）
        mode: "chars"（按字符）或 "tokens"（按 token，使用二分搜索）
        marker: 截断后追加的标记文本

    Returns:
        截断后的文本（如未超限则原样返回）
    """
    if not text or limit <= 0:
        return "" if limit <= 0 else text

    if mode == "tokens":
        if count_tokens(text) <= limit:
            return text
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if count_tokens(text[:mid]) <= limit:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo] + "\n" + marker
    else:
        if len(text) <= limit:
            return text
        return text[:limit] + "\n" + marker
