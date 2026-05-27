"""子Agent执行模块：子引擎创建、事件转发、委派任务执行。

仅保留共享预算的委派模式（原 clone 模式），子引擎为叶子执行器，不允许嵌套委派。
"""

from __future__ import annotations

import logging
from typing import AsyncGenerator

from ..config import SUBAGENT_SYSTEM_PROMPT

_log = logging.getLogger(__name__)


# ── 事件转发辅助 ─────────────────────────────────────────────────────

_AGENT_TYPE = "delegate"


def _fwd_done(event: dict, prefix: str, delegate_id: str, depth: int) -> str:
    return "done"


def _fwd_error(event: dict, prefix: str, delegate_id: str, depth: int) -> str:
    return "error"


def _fwd_text_delta(event: dict, prefix: str, delegate_id: str, depth: int) -> dict:
    return {
        "type": f"{prefix}text_delta",
        "delegate_id": delegate_id,
        "depth": depth,
        "agent_type": _AGENT_TYPE,
        "content": event["content"],
    }


def _fwd_tool_event(event: dict, prefix: str, delegate_id: str, depth: int) -> dict:
    forwarded: dict = {
        "type": f"{prefix}{event.get('type', '')}",
        "delegate_id": event.get("delegate_id", delegate_id),
        "depth": event.get("depth", depth),
        "agent_type": _AGENT_TYPE,
        "tool": event.get("tool", ""),
        "duration_ms": event.get("duration_ms", 0),
    }
    if "input" in event:
        forwarded["input"] = str(event["input"])
    if "output" in event:
        forwarded["output"] = str(event["output"])
    return forwarded


def _fwd_llm_request(event: dict, prefix: str, delegate_id: str, depth: int) -> dict:
    return {
        "type": f"{prefix}llm_request",
        "delegate_id": event.get("delegate_id", delegate_id),
        "depth": event.get("depth", depth),
        "agent_type": _AGENT_TYPE,
        "step": event.get("step"),
        "messages": event.get("messages"),
    }


def _fwd_llm_response(event: dict, prefix: str, delegate_id: str, depth: int) -> dict:
    return {
        "type": f"{prefix}llm_response",
        "delegate_id": event.get("delegate_id", delegate_id),
        "depth": event.get("depth", depth),
        "agent_type": _AGENT_TYPE,
        "step": event.get("step"),
        "input_tokens": event.get("input_tokens"),
        "output_tokens": event.get("output_tokens"),
        "cache_read_tokens": event.get("cache_read_tokens"),
        "cache_creation_tokens": event.get("cache_creation_tokens"),
        "content": event.get("content"),
        "reasoning": event.get("reasoning"),
        "tool_calls": event.get("tool_calls"),
    }


def _fwd_context_trim(event: dict, prefix: str, delegate_id: str, depth: int) -> dict:
    return {
        "type": f"{prefix}context_trim",
        "delegate_id": delegate_id,
        "depth": depth,
        "agent_type": _AGENT_TYPE,
        "step": event.get("step"),
    }


def _fwd_nested(event: dict, prefix: str, delegate_id: str, depth: int) -> dict:
    """透传嵌套孙Agent的事件（加一层前缀）。"""
    forwarded = dict(event)
    forwarded["type"] = f"sub_{event['type']}"
    forwarded["depth"] = event.get("depth", depth)
    forwarded["delegate_id"] = event.get("delegate_id", delegate_id)
    forwarded.setdefault("agent_type", _AGENT_TYPE)
    return forwarded


# Dispatch table: event_type → 转发函数
_FORWARDERS: dict[str, callable] = {
    "done": _fwd_done,
    "error": _fwd_error,
    "text_delta": _fwd_text_delta,
    "tool_call": _fwd_tool_event,
    "tool_result": _fwd_tool_event,
    "llm_request": _fwd_llm_request,
    "llm_response": _fwd_llm_response,
    "context_trim": _fwd_context_trim,
}


def forward_event(
    event: dict,
    prefix: str,
    delegate_id: str,
    depth: int,
) -> dict | str | None:
    """将子引擎事件转换为带前缀的转发事件。

    Args:
        event: 子引擎 yield 的原始事件
        prefix: 事件类型前缀（如 "sub_" 或 "sub_sub_"）
        delegate_id: 委派 ID
        depth: 嵌套深度

    Returns:
        - dict: 可转发的转发事件
        - "done": 子引擎执行完成
        - "error": 子引擎执行出错
        - None: 无需转发的未知事件
    """
    event_type = event["type"]

    # 查 dispatch table
    forwarder = _FORWARDERS.get(event_type)
    if forwarder is not None:
        return forwarder(event, prefix, delegate_id, depth)

    # 嵌套子Agent事件透传
    if event_type.startswith("sub_"):
        return _fwd_nested(event, prefix, delegate_id, depth)

    return None


# ── 子引擎工厂 ───────────────────────────────────────────────────────


def create_child_engine(
    parent,
    skill_names: list[str],
    delegate_id: str,
) -> "AgentEngine":
    """创建委派子引擎（共享父Agent的 token 预算）。

    子引擎为叶子执行器，不允许嵌套委派。

    Args:
        parent: 父 AgentEngine 实例
        skill_names: 要注册的技能名称列表
        delegate_id: 委派 ID

    Returns:
        配置好工具和技能的子 AgentEngine 实例
    """
    from ..config import EngineConfig
    from ..tools.skill_tool import SkillTool
    from ..skills.loader import _registry as skill_registry
    from ..skills.dependency import expand_with_dependencies
    from ..tools.access_policy import AccessPolicy
    from ..tools.run_command import RunCommandTool
    from ...config import PROJECT_ROOT
    # 延迟导入避免循环依赖
    from .engine import AgentEngine

    depth = parent.subagent_depth + 1
    session_id = f"delegate_{delegate_id}"

    # 子Agent 继承父Agent 的剩余预算，而非全量预算
    remaining_budget = max(
        0, parent.token_budget - parent.total_input_tokens - parent.total_output_tokens
    )

    child_cfg = EngineConfig(
        max_steps=parent.max_steps,
        slow_think_interval=0,
        token_budget=remaining_budget,
        loop_detection_threshold=parent.loop_threshold,
        context_trim_interval=(
            parent.context_trim_interval if parent.context_trim_interval > 0 else 5
        ),
        max_subagent_depth=parent.max_subagent_depth,
    )

    child = AgentEngine(
        session_id=session_id,
        system_prompt=SUBAGENT_SYSTEM_PROMPT.format(PROJECT_ROOT=PROJECT_ROOT),
        provider=parent.provider,
        temperature=parent.temperature,
        max_tokens=parent.max_tokens,
        config=child_cfg,
        runtime_trimmer=parent._runtime_trimmer,
        subagent_depth=depth,
    )

    # 共享中断信号
    child._interrupt = parent._interrupt

    # 展开 orch 技能的 depends_on 依赖，供 AccessPolicy 使用
    all_skill_names = expand_with_dependencies(skill_names) if skill_names else []

    # 注册基础工具（独立实例 + AccessPolicy）
    run_tool = RunCommandTool()
    policy = AccessPolicy.for_agent(str(PROJECT_ROOT), all_skill_names)
    run_tool.access_policy = policy
    child._system_prompt += policy.prompt_section()
    child.register_tool(run_tool.schema, run_tool.run)

    # Skill 工具：仅在 skill_names 非空时注册，并加闭包过滤（含依赖技能）
    if skill_names:
        from ..skills.filtered_runner import make_filtered_skill_runner

        skill_tool = SkillTool()
        filtered_run = make_filtered_skill_runner(
            set(all_skill_names), skill_tool.run,
        )
        child.register_tool(skill_tool.schema, filtered_run)

    # 设置允许的技能名称集合（含依赖）
    child._allowed_skill_names = set(all_skill_names)

    # 注册父Agent传入的技能
    for name in skill_names:
        skill = skill_registry.get(name)
        if skill:
            child.register_skill(skill)

    # 自动注入技能体摘要到子Agent system prompt，减少一次 Skill 工具调用
    for name in skill_names:
        skill = skill_registry.get(name)
        if skill and skill.body:
            body_excerpt = skill.body[:1500]
            child._system_prompt += (
                f"\n\n---\n\n# 技能 {name} 快速参考\n\n"
                f"{body_excerpt}\n\n"
                f"> 完整说明请调用 Skill(name=\"{name}\")"
            )

    _log.info(
        "[SubEngine] 创建完成: id=%s, session=%s, depth=%d, "
        "skills=%s (含依赖 %d), max_steps=%d",
        delegate_id, child.session_id, depth,
        skill_names, len(all_skill_names), child.max_steps,
    )

    return child


# ── Token 同步 ────────────────────────────────────────────────────────


def sync_tokens_from(target, source) -> None:
    """将 source 引擎的 token 消耗累加到 target（共享预算模式）。"""
    target.total_input_tokens += source.total_input_tokens
    target.total_output_tokens += source.total_output_tokens
    target.total_cache_read_tokens += source.total_cache_read_tokens
    target.total_cache_creation_tokens += source.total_cache_creation_tokens


# ── 执行函数 ──────────────────────────────────────────────────────────


async def run_delegate_task(
    parent,
    skill_names: list[str],
    prompt: str,
    delegate_id: str,
) -> AsyncGenerator[dict, None]:
    """委派任务执行：共享父Agent token 预算的隔离子引擎。

    特性：
    - 共享父 Agent 的 token_budget（不创建独立预算）
    - 共享父 Agent 的中断信号
    - 直接 yield 事件（不走 queue）
    - Token 消耗在执行后显式回写父引擎
    - 子引擎为叶子执行器，不允许嵌套委派
    """
    child = create_child_engine(parent, skill_names, delegate_id)

    child_messages: list[dict] = [{"role": "user", "content": prompt}]
    depth = parent.subagent_depth + 1
    prefix = "sub_" * depth

    _log.info(
        "[Delegate:%s] 开始运行: skills=%s, prompt_len=%d, budget=%d",
        delegate_id, skill_names, len(prompt), parent.token_budget,
    )

    result_text = ""
    child_steps = 0
    child_tool_calls = 0
    try:
        async for event in child.run(child_messages):
            if event.get("type") == "step_start":
                child_steps = event.get("step", child_steps)
            if event.get("type") == "tool_call":
                child_tool_calls += 1
            forwarded = forward_event(event, prefix, delegate_id, depth)
            if forwarded == "done":
                break
            elif forwarded == "error":
                sync_tokens_from(parent, child)
                _log.warning(
                    "[Delegate:%s] 运行出错: steps=%d, tool_calls=%d, "
                    "tokens=(in=%d, out=%d), error=%s",
                    delegate_id, child_steps, child_tool_calls,
                    child.total_input_tokens, child.total_output_tokens,
                    event.get("message", ""),
                )
                yield {"type": "__delegate_error__", "message": event["message"]}
                return
            elif forwarded is not None:
                if forwarded["type"] == f"{prefix}text_delta":
                    result_text += event["content"]
                yield forwarded
    except Exception as e:
        sync_tokens_from(parent, child)
        _log.error(
            "[Delegate:%s] 异常终止: steps=%d, tool_calls=%d, "
            "tokens=(in=%d, out=%d), error=%s",
            delegate_id, child_steps, child_tool_calls,
            child.total_input_tokens, child.total_output_tokens, str(e),
            exc_info=True,
        )
        yield {"type": "__delegate_error__", "message": str(e)}
        return

    sync_tokens_from(parent, child)
    _log.info(
        "[Delegate:%s] 运行完成: steps=%d, tool_calls=%d, "
        "tokens=(in=%d, out=%d, cache_read=%d), result_len=%d",
        delegate_id, child_steps, child_tool_calls,
        child.total_input_tokens, child.total_output_tokens,
        child.total_cache_read_tokens, len(result_text),
    )
    yield {
        "type": "__delegate_done__",
        "result": result_text.strip() or "(委派任务完成，无文本输出)",
    }
