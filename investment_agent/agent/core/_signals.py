"""引擎内部信号类型 — 替代魔法字典键的内部通信机制。

这些类型仅用于引擎内部方法之间的 async generator 通信，
不会 yield 给外部调用者（TaskManager / SSE 端点）。

旧实现使用 "_result"、"_inject"、"_messages" 等字符串键，
现在用类型安全的 dataclass 替代，获得 IDE 补全和类型检查。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class _Value:
    """从 async generator 中返回一个值给调用方。

    替代旧 dict["_result"] / dict["_internal_result"]。
    """
    value: Any


@dataclass
class _Terminal:
    """终止事件：done（正常结束）或 continue（截断后继续）。

    替代旧 dict["_terminal"]。
    """
    event: dict | None


@dataclass
class _Inject:
    """注入一条消息到对话列表。

    替代旧 dict["_inject"]。
    """
    message: dict
