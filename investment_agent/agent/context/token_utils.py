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


def estimate_message_tokens(message: dict) -> int:
    """估算单条消息的 token 数（heuristic 版本）。"""
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


# ── Real token counting ─────────────────────────────────────────────

# Message formatting overhead in tokens (Anthropic API overhead)
_ROLE_OVERHEAD = 4
_SYSTEM_OVERHEAD = 8
_TOOL_DEF_OVERHEAD = 8

# Known model context window sizes
_MODEL_CONTEXT_LIMITS: dict[str, int] = {
    # Claude models
    "claude-sonnet-4-6": 200_000,
    "claude-sonnet-4-5": 200_000,
    "claude-opus-4-7": 200_000,
    "claude-haiku-4-5": 200_000,
    "claude-sonnet-4-0": 200_000,
    "claude-opus-4-0": 200_000,
    "claude-opus-4-5": 200_000,
    "claude-3-5-sonnet": 200_000,
    "claude-3-5-haiku": 200_000,
    "claude-3-opus": 200_000,
    "claude-3-sonnet": 200_000,
    "claude-3-haiku": 200_000,
    # OpenAI models
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_384,
    # DeepSeek models
    "deepseek-v3": 128_000,
    "deepseek-v4": 128_000,
    "deepseek-r1": 128_000,
    # Qwen models
    "qwen-max": 128_000,
    "qwen-plus": 128_000,
}
_DEFAULT_CONTEXT_LIMIT = 128_000


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


def get_model_context_limit(model_name: str | None) -> int:
    """获取已知模型的上下文窗口大小（token 数）。

    未知模型返回默认 128k 并记录 warning。
    """
    if not model_name:
        return _DEFAULT_CONTEXT_LIMIT

    name_lower = model_name.lower()
    for key, limit in _MODEL_CONTEXT_LIMITS.items():
        if key in name_lower or name_lower in key:
            return limit

    logger.warning("Unknown model %r — assuming %d context limit", model_name, _DEFAULT_CONTEXT_LIMIT)
    return _DEFAULT_CONTEXT_LIMIT
