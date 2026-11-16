"""llm_request 链路的增量存储与折叠。

写入时按对话流只保留相对上一次的尾部；前缀被改写（裁剪、改第一条消息）时重新存完整快照。
读取和导出时按时间把 snapshot/delta 折回截至该步的完整 messages。
没有 kind 的旧记录视为整份快照。
"""

from __future__ import annotations

import copy
from typing import Any


def is_llm_request_event(event_type: str) -> bool:
    """主 Agent 与任意深度子 Agent 的请求事件。"""
    return "llm_request" in (event_type or "")


def compact_request(
    state: dict[tuple[str, str], list],
    event_type: str,
    detail: dict[str, Any],
) -> dict[str, Any]:
    """把一次 llm_request 的 messages 压成 snapshot 或 delta，并立刻深拷贝。

    state 按 (event_type, delegate_id) 记住该流上一份完整消息。
    返回的字典不再引用引擎里的活列表。
    """
    delegate_id = detail.get("delegate_id") or ""
    key = (event_type, delegate_id)
    raw = detail.get("messages") or []
    if not isinstance(raw, list):
        raw = []
    copied = copy.deepcopy(raw)

    prev = state.get(key)
    header = _header(detail)
    if prev is None or not _is_append(prev, copied):
        state[key] = copied
        return {
            **header,
            "kind": "snapshot",
            "message_count": len(copied),
            "added_count": len(copied),
            "messages": copied,
        }

    delta = copied[len(prev):]
    state[key] = copied
    return {
        **header,
        "kind": "delta",
        "from_index": len(prev),
        "message_count": len(copied),
        "added_count": len(delta),
        "messages": delta,
    }


def fold_messages(details: list[dict]) -> list:
    """按从早到晚的顺序把 snapshot/delta（及旧版整份记录）折成一份 messages。"""
    acc: list = []
    for detail in details:
        if not isinstance(detail, dict):
            continue
        messages = detail.get("messages") or []
        if not isinstance(messages, list):
            messages = []
        if detail.get("kind") == "delta":
            start = detail.get("from_index") or 0
            try:
                start = int(start)
            except (TypeError, ValueError):
                start = 0
            if start < 0:
                start = 0
            acc = acc[:start] + list(messages)
        else:
            acc = list(messages)
    return acc


def _header(detail: dict) -> dict:
    """标识字段放在 messages 前面，列表接口截断后仍能 json_extract。"""
    header: dict[str, Any] = {}
    if detail.get("delegate_id"):
        header["delegate_id"] = detail.get("delegate_id")
    if detail.get("label"):
        header["label"] = detail.get("label")
    if detail.get("depth") is not None:
        header["depth"] = detail.get("depth")
    if detail.get("agent_type"):
        header["agent_type"] = detail.get("agent_type")
    if detail.get("step") is not None:
        header["step"] = detail.get("step")
    return header


def _is_append(prev: list, current: list) -> bool:
    if len(current) < len(prev):
        return False
    return current[:len(prev)] == prev
