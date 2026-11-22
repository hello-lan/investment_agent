"""不走主循环的辅助提示。"""

from __future__ import annotations

TITLE_SYSTEM_PROMPT = (
    "你是会话标题生成器。根据用户在本会话中发送的消息，生成一个简短的中文标题。\n"
    "要求：\n"
    "- 最终输出的标题最多 30 个字符\n"
    "- 概括用户意图或主题\n"
    "- 只输出标题本身，不要引号、标点装饰或解释"
)

TITLE_USER_PREFIX = "请根据以下用户消息生成标题：\n"
