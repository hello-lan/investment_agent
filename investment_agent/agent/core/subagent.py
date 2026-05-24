"""子Agent执行模块：SubAgentPool、子引擎创建、事件转发。

从 engine.py 中拆分，消除 _run_subagent_task 和 _run_clone_task 之间的重复逻辑。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import AsyncGenerator, Callable, Awaitable

from ..config import SUBAGENT_SYSTEM_PROMPT
from .models import ModelProvider
from ..context.runtime_trimmer import RuntimeTrimmer, NoOpRuntimeTrimmer, DefaultRuntimeTrimmer


class SubAgentPool:
    """子Agent并发池：asyncio.Semaphore 控制同层并发数。

    每层 Agent 拥有独立的 pool（独立 semaphore），不存在跨层死锁。
    """

    def __init__(self, max_concurrent: int):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active: dict[str, asyncio.Task] = {}

    async def submit(self, delegate_id: str, coro) -> asyncio.Task:
        """提交子Agent任务，受信号量控制。"""
        await self._semaphore.acquire()
        task = asyncio.create_task(self._wrap(delegate_id, coro))
        self._active[delegate_id] = task
        return task

    async def _wrap(self, delegate_id: str, coro):
        """包装协程：完成后释放信号量。"""
        try:
            return await coro
        finally:
            self._semaphore.release()
            self._active.pop(delegate_id, None)


# ── 事件转发辅助 ─────────────────────────────────────────────────────


def forward_event(
    event: dict,
    prefix: str,
    delegate_id: str,
    depth: int,
    agent_type: str,
) -> dict | str | None:
    """将子引擎事件转换为带前缀的转发事件。

    Args:
        event: 子引擎 yield 的原始事件
        prefix: 事件类型前缀（如 "sub_" 或 "sub_sub_"）
        delegate_id: 委派 ID
        depth: 嵌套深度
        agent_type: 代理类型标签（"serial" / "clone"）

    Returns:
        - dict: 可转发的转发事件
        - "done": 子引擎执行完成
        - "error": 子引擎执行出错（message 在 event["message"] 中）
        - None: 无需转发的未知事件
    """
    event_type = event["type"]

    if event_type == "done":
        return "done"

    if event_type == "error":
        return "error"

    if event_type == "text_delta":
        return {
            "type": f"{prefix}text_delta",
            "delegate_id": delegate_id,
            "depth": depth,
            "agent_type": agent_type,
            "content": event["content"],
        }

    if event_type in ("tool_call", "tool_result"):
        sub_type = event.get("type", "")
        forwarded_type = f"{prefix}{sub_type}"
        forwarded: dict = {
            "type": forwarded_type,
            "delegate_id": event.get("delegate_id", delegate_id),
            "depth": event.get("depth", depth),
            "agent_type": agent_type,
            "tool": event.get("tool", ""),
            "duration_ms": event.get("duration_ms", 0),
        }
        if "input" in event:
            forwarded["input"] = str(event["input"])
        if "output" in event:
            forwarded["output"] = str(event["output"])
        return forwarded

    if event_type in ("llm_request", "llm_response"):
        sub_type = event.get("type", "")
        forwarded_type = f"{prefix}{sub_type}"
        forwarded = {
            "type": forwarded_type,
            "delegate_id": event.get("delegate_id", delegate_id),
            "depth": event.get("depth", depth),
            "agent_type": agent_type,
            "step": event.get("step"),
        }
        if event_type == "llm_request":
            forwarded["messages"] = event.get("messages")
        else:
            forwarded["input_tokens"] = event.get("input_tokens")
            forwarded["output_tokens"] = event.get("output_tokens")
            forwarded["cache_read_tokens"] = event.get("cache_read_tokens")
            forwarded["cache_creation_tokens"] = event.get("cache_creation_tokens")
            forwarded["content"] = event.get("content")
            forwarded["reasoning"] = event.get("reasoning")
            forwarded["tool_calls"] = event.get("tool_calls")
        return forwarded

    if event_type.startswith("sub_"):
        # 透传嵌套孙Agent的事件（加一层前缀）
        forwarded = dict(event)
        forwarded["type"] = f"sub_{event_type}"
        forwarded["depth"] = event.get("depth", depth)
        forwarded["delegate_id"] = event.get("delegate_id", delegate_id)
        forwarded.setdefault("agent_type", agent_type)
        return forwarded

    return None


# ── 子引擎工厂 ───────────────────────────────────────────────────────


def create_child_engine(
    parent,
    child_type: str,
    skill_names: list[str],
    delegate_id: str,
) -> "AgentEngine":
    """创建子引擎并注册工具。

    Args:
        parent: 父 AgentEngine 实例
        child_type: "subagent"（独立预算）或 "clone"（共享预算）
        skill_names: 要注册的技能名称列表
        delegate_id: 委派 ID

    Returns:
        配置好工具和技能的子 AgentEngine 实例
    """
    from ..skills.tool import SkillTool
    from ..skills.loader import _registry as skill_registry
    from ..tools.run_command import RunCommandTool
    from ..tools.registry import get_tool
    from ...config import PROJECT_ROOT
    # 延迟导入避免循环依赖
    from .engine import AgentEngine

    depth = parent.subagent_depth + 1

    if child_type == "clone":
        session_id = f"clone_{delegate_id}"
        child = AgentEngine(
            session_id=session_id,
            system_prompt=SUBAGENT_SYSTEM_PROMPT.format(PROJECT_ROOT=PROJECT_ROOT),
            provider=parent.provider,
            temperature=parent.temperature,
            max_tokens=parent.max_tokens,
            max_steps=parent.max_steps,
            slow_think_interval=0,
            token_budget=parent.token_budget,
            loop_detection_threshold=parent.loop_threshold,
            context_trim_interval=(
                parent.context_trim_interval if parent.context_trim_interval > 0 else 5
            ),
            runtime_trimmer=(
                parent._runtime_trimmer
                if parent._runtime_trimmer and not isinstance(parent._runtime_trimmer, NoOpRuntimeTrimmer)
                else DefaultRuntimeTrimmer(tool_trim_limits=parent.tool_trim_limits)
            ),
            subagent_depth=depth,
            max_subagent_depth=parent.max_subagent_depth,
            max_concurrent_subagents=parent.max_concurrent_subagents,
            sub_agent_mode="serial",
        )
    else:
        # subagent: 独立预算
        session_id = f"sub_{delegate_id}"

        # 继承父 Agent 的裁剪配置（仅当父 Agent 启用了裁剪时）
        if (
            parent.context_trim_interval > 0
            and parent._runtime_trimmer
            and not isinstance(parent._runtime_trimmer, NoOpRuntimeTrimmer)
        ):
            sub_trimmer = parent._runtime_trimmer
            sub_trim_interval = parent.context_trim_interval
        else:
            sub_trimmer = DefaultRuntimeTrimmer(tool_trim_limits=parent.tool_trim_limits)
            sub_trim_interval = 5

        budget = max(
            50_000,
            parent.token_budget - parent.total_input_tokens - parent.total_output_tokens,
        )

        child = AgentEngine(
            session_id=session_id,
            system_prompt=SUBAGENT_SYSTEM_PROMPT.format(PROJECT_ROOT=PROJECT_ROOT),
            provider=parent.provider,
            max_steps=parent.max_steps,
            slow_think_interval=0,
            token_budget=budget,
            context_trim_interval=sub_trim_interval,
            runtime_trimmer=sub_trimmer,
            subagent_depth=depth,
            max_subagent_depth=parent.max_subagent_depth,
            max_concurrent_subagents=parent.max_concurrent_subagents,
            sub_agent_mode=parent.sub_agent_mode,
            loop_detection_threshold=parent.loop_threshold,
        )

    # 共享中断信号（clone 和 subagent 模式均需要）
    child._interrupt = parent._interrupt

    # 注册基础工具
    run_tool = RunCommandTool()
    child.register_tool(run_tool.schema, run_tool.run)
    skill_tool = SkillTool()
    child.register_tool(skill_tool.schema, skill_tool.run)
    # 深度未达上限时允许嵌套委派
    if depth < parent.max_subagent_depth:
        delegate_tool = get_tool("DelegateTask")
        if delegate_tool:
            child.register_tool(delegate_tool.schema, delegate_tool.run)
    # 注册父Agent传入的技能
    for name in skill_names:
        skill = skill_registry.get(name)
        if skill:
            child.register_skill(skill)

    return child


# ── Token 同步 ────────────────────────────────────────────────────────


def sync_tokens_from(target, source) -> None:
    """从 source 引擎同步 token 计数器到 target。"""
    target.total_input_tokens = source.total_input_tokens
    target.total_output_tokens = source.total_output_tokens
    target.total_cache_read_tokens = source.total_cache_read_tokens
    target.total_cache_creation_tokens = source.total_cache_creation_tokens


def accumulate_tokens(target, source) -> None:
    """将 source 引擎的 token 消耗累加到 target（用于独立预算子Agent）。"""
    target.total_input_tokens += source.total_input_tokens
    target.total_output_tokens += source.total_output_tokens
    target.total_cache_read_tokens += source.total_cache_read_tokens
    target.total_cache_creation_tokens += source.total_cache_creation_tokens


# ── 执行函数 ──────────────────────────────────────────────────────────


async def run_subagent_task(
    parent,
    skill_names: list[str],
    prompt: str,
    event_queue: asyncio.Queue,
    delegate_id: str,
    result_queue: asyncio.Queue | None = None,
    budget: int | None = None,
) -> None:
    """子Agent后台任务：运行隔离引擎，事件入队，完成/错误时发哨兵事件。

    支持嵌套委派：子引擎可注册 DelegateTask 工具，进一步创建孙Agent。
    事件前缀根据嵌套深度自动累加（depth=1: sub_tool_call, depth=2: sub_sub_tool_call）。

    Args:
        parent: 父 AgentEngine 实例
        result_queue: 并发模式下用于接收完成/错误信号（与 event_queue 分离）。
                     串行模式下为 None，完成/错误信号写入 event_queue。
        budget: 子Agent的token预算。如果为None，则使用默认计算。
    """
    depth = parent.subagent_depth + 1
    signal_queue = result_queue if result_queue is not None else event_queue

    sub = create_child_engine(parent, "subagent", skill_names, delegate_id)

    # 如果传入了自定义 budget，覆盖默认值
    if budget is not None:
        sub.token_budget = budget

    sub_messages: list[dict] = [{"role": "user", "content": prompt}]
    prefix = "sub_" * depth
    agent_type = "serial"

    result_text = ""
    try:
        async for event in sub.run(sub_messages):
            forwarded = forward_event(event, prefix, delegate_id, depth, agent_type)
            if forwarded == "done":
                break
            elif forwarded == "error":
                await signal_queue.put({
                    "type": "__delegate_error__",
                    "delegate_id": delegate_id,
                    "message": event["message"],
                })
                return
            elif forwarded is not None:
                if forwarded["type"] == f"{prefix}text_delta":
                    result_text += event["content"]
                await event_queue.put(forwarded)
    except Exception as e:
        await signal_queue.put({
            "type": "__delegate_error__",
            "delegate_id": delegate_id,
            "message": str(e),
        })
        return
    finally:
        accumulate_tokens(parent, sub)

    await signal_queue.put({
        "type": "__delegate_done__",
        "delegate_id": delegate_id,
        "result": result_text.strip() or "(子任务完成，无文本输出)",
    })


async def run_clone_task(
    parent,
    skill_names: list[str],
    prompt: str,
    delegate_id: str,
) -> AsyncGenerator[dict, None]:
    """分身执行委派任务：共享 token 预算的轻量隔离引擎。

    与 run_subagent_task 的区别：
    - 共享父 Agent 的 token_budget（不创建独立预算）
    - 共享父 Agent 的中断信号
    - 直接 yield 事件（不走 queue）
    - Token 消耗在执行后显式回写
    """
    clone = create_child_engine(parent, "clone", skill_names, delegate_id)

    clone_messages: list[dict] = [{"role": "user", "content": prompt}]
    depth = parent.subagent_depth + 1
    prefix = "sub_" * depth
    agent_type = "clone"

    result_text = ""
    try:
        async for event in clone.run(clone_messages):
            forwarded = forward_event(event, prefix, delegate_id, depth, agent_type)
            if forwarded == "done":
                break
            elif forwarded == "error":
                sync_tokens_from(parent, clone)
                yield {"type": "__clone_error__", "message": event["message"]}
                return
            elif forwarded is not None:
                if forwarded["type"] == f"{prefix}text_delta":
                    result_text += event["content"]
                yield forwarded
    except Exception as e:
        sync_tokens_from(parent, clone)
        yield {"type": "__clone_error__", "message": str(e)}
        return

    sync_tokens_from(parent, clone)
    yield {
        "type": "__clone_done__",
        "result": result_text.strip() or "(分身任务完成，无文本输出)",
    }
