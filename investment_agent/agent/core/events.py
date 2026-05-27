"""引擎事件 → 可观测性 trace_detail 的构建逻辑。

将 event_type + event dict 映射为 trace_log 表所需的 detail JSON。
供 task_manager.py 和 observability hooks 统一使用，避免重复。
"""

from __future__ import annotations

from typing import Callable


# ── 各事件类型的 detail 构建函数 ─────────────────────────────────────


def _detail_llm_request(event: dict) -> dict:
    return {"messages": event.get("messages")}


def _detail_llm_response(event: dict) -> dict:
    return {
        "input_tokens": event.get("input_tokens"),
        "output_tokens": event.get("output_tokens"),
        "cache_read_tokens": event.get("cache_read_tokens"),
        "cache_creation_tokens": event.get("cache_creation_tokens"),
        "content": event.get("content"),
        "reasoning": event.get("reasoning"),
        "tool_calls": event.get("tool_calls"),
    }


def _detail_tool_call(event: dict) -> dict:
    return {"tool": event.get("tool"), "input": event.get("input")}


def _detail_tool_result(event: dict) -> dict:
    return {
        "tool": event.get("tool"),
        "output": str(event.get("output", ""))[:500],
        "duration_ms": event.get("duration_ms"),
    }


def _detail_done(event: dict) -> dict:
    return {"usage": event.get("usage")}


def _detail_error(event: dict) -> dict:
    detail = {"message": event.get("message")}
    if event.get("recent_tool_calls"):
        detail["recent_tool_calls"] = event["recent_tool_calls"]
    return detail


def _detail_slow_think(event: dict) -> dict:
    return {"message": event.get("message") or event.get("content")}


def _detail_step_start(event: dict) -> dict:
    return {"step": event.get("step")}


def _detail_context_trim(event: dict) -> dict:
    return {"step": event.get("step")}


def _detail_budget_status(event: dict) -> dict:
    return {
        "total_used": event.get("total_used"),
        "budget": event.get("budget"),
        "remaining": event.get("remaining"),
        "delegate_id": event.get("delegate_id"),
    }


# ── Dispatch table ───────────────────────────────────────────────────

_DETAIL_BUILDERS: dict[str, Callable[[dict], dict]] = {
    "llm_request": _detail_llm_request,
    "llm_response": _detail_llm_response,
    "tool_call": _detail_tool_call,
    "tool_result": _detail_tool_result,
    "done": _detail_done,
    "error": _detail_error,
    "slow_think": _detail_slow_think,
    "step_start": _detail_step_start,
    "context_trim": _detail_context_trim,
    "budget_status": _detail_budget_status,
}


def _build_sub_detail(event_type: str, event: dict) -> dict | None:
    """构建子Agent事件（前缀 "sub_"）的 trace_detail。"""
    base = {
        "delegate_id": event.get("delegate_id"),
        "depth": event.get("depth"),
        "agent_type": event.get("agent_type"),
    }
    if "tool_call" in event_type:
        return {**base, "tool": event.get("tool"), "input": event.get("input")}
    if "tool_result" in event_type:
        return {
            **base,
            "tool": event.get("tool"),
            "output": str(event.get("output", ""))[:500],
            "duration_ms": event.get("duration_ms"),
        }
    if "llm_request" in event_type:
        return {**base, "step": event.get("step"), "messages": event.get("messages")}
    if "llm_response" in event_type:
        return {
            **base,
            "step": event.get("step"),
            "input_tokens": event.get("input_tokens"),
            "output_tokens": event.get("output_tokens"),
            "cache_read_tokens": event.get("cache_read_tokens"),
            "cache_creation_tokens": event.get("cache_creation_tokens"),
            "content": event.get("content"),
            "reasoning": event.get("reasoning"),
            "tool_calls": event.get("tool_calls"),
        }
    return None


def build_trace_detail(event_type: str, event: dict) -> dict | None:
    """从引擎事件构建可观测性 trace_detail 字典。

    Args:
        event_type: 事件类型字符串（如 "tool_call", "sub_tool_result" 等）
        event: 引擎 yield 的事件字典

    Returns:
        trace_detail 字典，或 None（该事件类型无需记录 trace）
    """
    # 普通事件：查 dispatch table
    builder = _DETAIL_BUILDERS.get(event_type)
    if builder is not None:
        return builder(event)

    # 子Agent事件：通过前缀 "sub_" 识别
    if event_type.startswith("sub_"):
        return _build_sub_detail(event_type, event)

    return None
