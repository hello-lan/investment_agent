"""引擎事件 → 可观测性 trace_detail 的构建逻辑。

将 event_type + event dict 映射为 trace_log 表所需的 detail JSON。
供 task_manager.py 和 observability hooks 统一使用，避免重复。
"""

from __future__ import annotations


def build_trace_detail(event_type: str, event: dict) -> dict | None:
    """从引擎事件构建可观测性 trace_detail 字典。

    Args:
        event_type: 事件类型字符串（如 "tool_call", "sub_tool_result" 等）
        event: 引擎 yield 的事件字典

    Returns:
        trace_detail 字典，或 None（该事件类型无需记录 trace）
    """
    if event_type == "llm_request":
        return {"messages": event.get("messages")}

    if event_type == "llm_response":
        return {
            "input_tokens": event.get("input_tokens"),
            "output_tokens": event.get("output_tokens"),
            "cache_read_tokens": event.get("cache_read_tokens"),
            "cache_creation_tokens": event.get("cache_creation_tokens"),
            "content": event.get("content"),
            "reasoning": event.get("reasoning"),
            "tool_calls": event.get("tool_calls"),
        }

    if event_type == "tool_call":
        return {"tool": event.get("tool"), "input": event.get("input")}

    if event_type == "tool_result":
        return {
            "tool": event.get("tool"),
            "output": str(event.get("output", ""))[:500],
            "duration_ms": event.get("duration_ms"),
        }

    # 子Agent事件：通过前缀 "sub_" 识别
    if event_type.startswith("sub_"):
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

    if event_type == "done":
        return {"usage": event.get("usage")}

    if event_type == "error":
        detail = {"message": event.get("message")}
        if event.get("recent_tool_calls"):
            detail["recent_tool_calls"] = event["recent_tool_calls"]
        return detail

    if event_type == "slow_think":
        return {"message": event.get("message") or event.get("content")}

    if event_type == "step_start":
        return {"step": event.get("step")}

    if event_type == "context_trim":
        return {"step": event.get("step")}

    if event_type == "budget_status":
        return {
            "total_used": event.get("total_used"),
            "budget": event.get("budget"),
            "remaining": event.get("remaining"),
            "delegate_id": event.get("delegate_id"),
        }

    return None
