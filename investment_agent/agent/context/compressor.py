from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


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
