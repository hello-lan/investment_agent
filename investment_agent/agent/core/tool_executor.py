"""工具执行策略：串行、并发、分身三种模式 + 死循环检测。

从 engine.py 中拆分，通过组合模式注入 AgentEngine。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import Counter
from typing import AsyncGenerator, Protocol, TYPE_CHECKING

from .models import ToolCall
from .subagent import SubAgentPool, run_subagent_task, run_clone_task

if TYPE_CHECKING:
    from .engine import AgentEngine


# ── 常量 ──────────────────────────────────────────────────────────────

CLONE_MIN_REMAINING = 30_000       # clone 模式最低剩余 token
DELEGATE_MIN_REMAINING = 50_000    # serial/concurrent 模式最低剩余 token


# ── 死循环检测 ────────────────────────────────────────────────────────

class LoopDetector:
    """滑动窗口死循环检测：同一工具连续调用超过阈值则中止。"""

    def __init__(self, threshold: int, whitelist: set[str]):
        self._threshold = threshold
        self._whitelist = whitelist
        self._recent: list[str] = []
        self._detected_tool: str = ""

    def check(self, tool_calls: list[ToolCall]) -> bool:
        """记录工具调用并检测死循环。返回 True 表示检测到。"""
        for tc in tool_calls:
            self._recent.append(tc.name)
        candidates = [n for n in self._recent if n not in self._whitelist]
        self._recent = self._recent[-self._threshold * 2:]  # 保持滑动窗口
        counts = Counter(candidates[-self._threshold:])
        if counts and counts.most_common(1)[0][1] >= self._threshold:
            self._detected_tool = counts.most_common(1)[0][0]
            return True
        return False

    def error_event(self) -> dict:
        """返回死循环错误事件。"""
        return {
            "type": "error",
            "message": (
                f"Dead loop detected: '{self._detected_tool}' "
                f"called {self._threshold} times in a row."
            ),
            "recent_tool_calls": list(self._recent),
        }


# ── 委派任务准备 ──────────────────────────────────────────────────────

async def prepare_delegate_task(
    engine: "AgentEngine",
    tc: ToolCall,
    min_remaining: int,
) -> tuple[list[str], str, str] | str:
    """统一的 DelegateTask 准备：深度检查 → 预算检查 → 技能过滤 → prompt 生成。

    Args:
        engine: 父 AgentEngine 实例
        tc: DelegateTask 工具调用
        min_remaining: 最低剩余 token 要求

    Returns:
        成功: (skill_names, prompt, delegate_id)
        失败: 错误信息字符串
    """
    if engine.subagent_depth >= engine.max_subagent_depth:
        return (
            f"错误：已达到最大委派深度 {engine.max_subagent_depth}，"
            f"无法创建子Agent"
        )

    remaining = engine.token_budget - engine.total_input_tokens - engine.total_output_tokens
    if remaining < min_remaining:
        mode_label = "分身" if engine.sub_agent_mode == "clone" else "委派"
        return (
            f"错误：剩余 token 预算不足 ({remaining}/{engine.token_budget})，"
            f"无法{mode_label}执行子任务"
        )

    raw_skill_names = tc.input.get("skill_names", []) or []
    task_desc = tc.input.get("task", "")
    from ..skills.loader import _registry as skill_registry
    skill_names = [
        n for n in raw_skill_names
        if skill_registry.get(n) and skill_registry[n].skill_type != "orch"
    ]
    prompt = await engine.task_planner.generate(task_desc, skill_names, engine._messages)
    delegate_id = f"delegate_{uuid.uuid4().hex[:8]}"
    return skill_names, prompt, delegate_id


# ── ToolExecutor 协议 ─────────────────────────────────────────────────

class ToolExecutor(Protocol):
    """工具执行策略接口。"""

    async def execute(
        self, tool_calls: list[ToolCall], engine: "AgentEngine",
    ) -> AsyncGenerator[dict, None]:
        """执行工具列表，yield 事件。最后 yield {"_internal_result": [...]} 返回结果。"""
        ...


# ── 串行执行器 ────────────────────────────────────────────────────────

class SerialToolExecutor:
    """串行执行工具列表，支持 clone 模式。

    DelegateTask 逐个执行，阻塞等待完成。
    非 DelegateTask 直接调用 engine 的 tool_handler。
    clone_mode=True 时使用分身引擎（共享预算）。
    """

    def __init__(self, clone_mode: bool = False):
        self.clone_mode = clone_mode

    async def execute(
        self, tool_calls: list[ToolCall], engine: "AgentEngine",
    ) -> AsyncGenerator[dict, None]:
        min_remaining = CLONE_MIN_REMAINING if self.clone_mode else DELEGATE_MIN_REMAINING

        tool_results = []
        for tc in tool_calls:
            yield {"type": "tool_call", "tool": tc.name, "input": tc.input}
            t0 = time.monotonic()

            if tc.name == "DelegateTask":
                prepared = await prepare_delegate_task(engine, tc, min_remaining)
                if isinstance(prepared, str):
                    result = prepared
                else:
                    skill_names, prompt, delegate_id = prepared
                    result = ""
                    if self.clone_mode:
                        async for event in run_clone_task(engine, skill_names, prompt, delegate_id):
                            if event["type"] == "__clone_done__":
                                result = event["result"]
                            elif event["type"] == "__clone_error__":
                                result = f"子任务执行错误: {event['message']}"
                            else:
                                yield event
                    else:
                        event_queue: asyncio.Queue = asyncio.Queue()
                        asyncio.ensure_future(
                            run_subagent_task(engine, skill_names, prompt, event_queue, delegate_id)
                        )
                        while True:
                            event = await event_queue.get()
                            if event["type"] == "__delegate_done__":
                                result = event["result"]
                                break
                            elif event["type"] == "__delegate_error__":
                                result = f"子任务执行错误: {event['message']}"
                                break
                            else:
                                yield event
            else:
                handler = engine.tool_handlers.get(tc.name)
                if not handler:
                    result = f"Tool '{tc.name}' not found."
                else:
                    try:
                        result = str(await handler(**tc.input))
                    except Exception as e:
                        result = f"Tool error: {e}"

            duration_ms = int((time.monotonic() - t0) * 1000)
            yield {
                "type": "tool_result",
                "tool": tc.name,
                "output": result,
                "duration_ms": duration_ms,
            }
            if tc.name == "DelegateTask":
                yield {
                    "type": "budget_status",
                    "total_used": engine.total_input_tokens + engine.total_output_tokens,
                    "budget": engine.token_budget,
                    "remaining": engine.token_budget - engine.total_input_tokens - engine.total_output_tokens,
                }
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": result,
            })
        yield {"_internal_result": tool_results}


# ── 并发执行器 ────────────────────────────────────────────────────────

class ConcurrentToolExecutor:
    """并发执行工具列表。

    DelegateTask 通过 SubAgentPool 并发启动，非 DelegateTask 顺序执行。
    共享 event_queue 收集所有 delegate 的实时事件，统一转发。
    结果按原始顺序返回。
    """

    def __init__(self, max_concurrent: int = 3):
        self._pool = SubAgentPool(max_concurrent)

    async def execute(
        self, tool_calls: list[ToolCall], engine: "AgentEngine",
    ) -> AsyncGenerator[dict, None]:
        event_queue: asyncio.Queue = asyncio.Queue()
        delegate_tasks = []  # [(idx, tc, asyncio.Task, result_queue, t0)]
        ordered_results = [None] * len(tool_calls)

        delegate_count = sum(1 for tc in tool_calls if tc.name == "DelegateTask")

        # 第一遍：分离 delegate 和非 delegate
        for idx, tc in enumerate(tool_calls):
            yield {"type": "tool_call", "tool": tc.name, "input": tc.input}
            t0 = time.monotonic()

            if tc.name == "DelegateTask":
                remaining = engine.token_budget - engine.total_input_tokens - engine.total_output_tokens
                per_delegate_budget = max(CLONE_MIN_REMAINING, remaining // max(1, delegate_count))
                prepared = await prepare_delegate_task(engine, tc, per_delegate_budget)

                if isinstance(prepared, str):
                    result = prepared
                    yield {
                        "type": "tool_result",
                        "tool": tc.name,
                        "output": result,
                        "duration_ms": int((time.monotonic() - t0) * 1000),
                    }
                    ordered_results[idx] = {
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": result,
                    }
                    continue

                skill_names, prompt, delegate_id = prepared
                result_queue: asyncio.Queue = asyncio.Queue()
                task = await self._pool.submit(
                    delegate_id,
                    run_subagent_task(
                        engine, skill_names, prompt, event_queue, delegate_id,
                        result_queue, budget=per_delegate_budget,
                    ),
                )
                delegate_tasks.append((idx, tc, task, result_queue, t0))
            else:
                handler = engine.tool_handlers.get(tc.name)
                if not handler:
                    result = f"Tool '{tc.name}' not found."
                else:
                    try:
                        result = str(await handler(**tc.input))
                    except Exception as e:
                        result = f"Tool error: {e}"
                duration_ms = int((time.monotonic() - t0) * 1000)
                yield {
                    "type": "tool_result",
                    "tool": tc.name,
                    "output": result,
                    "duration_ms": duration_ms,
                }
                ordered_results[idx] = {
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": result,
                }

        # 第二遍：转发实时事件直到所有 delegate 完成
        done_count = 0
        while done_count < len(delegate_tasks):
            event = await event_queue.get()
            if event["type"] == "__delegate_done__":
                done_count += 1
            elif event["type"] == "__delegate_error__":
                done_count += 1
                yield event
            else:
                yield event

        # 第三遍：按原始顺序收集结果
        for idx, tc, task, result_queue, t0 in delegate_tasks:
            await task
            result_event = await result_queue.get()
            if result_event["type"] == "__delegate_done__":
                result = result_event["result"]
            else:
                result = f"子任务执行错误: {result_event['message']}"
            duration_ms = int((time.monotonic() - t0) * 1000)
            yield {
                "type": "tool_result",
                "tool": tc.name,
                "output": result,
                "duration_ms": duration_ms,
                "delegate_id": result_event.get("delegate_id", ""),
            }
            yield {
                "type": "budget_status",
                "total_used": engine.total_input_tokens + engine.total_output_tokens,
                "budget": engine.token_budget,
                "remaining": engine.token_budget - engine.total_input_tokens - engine.total_output_tokens,
                "delegate_id": result_event.get("delegate_id", ""),
            }
            ordered_results[idx] = {
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": result,
            }

        yield {"_internal_result": ordered_results}


# ── 工厂函数 ──────────────────────────────────────────────────────────

def create_tool_executor(mode: str, max_concurrent: int = 3) -> SerialToolExecutor | ConcurrentToolExecutor:
    """根据模式创建工具执行器。

    Args:
        mode: "serial" | "concurrent" | "clone"
        max_concurrent: 并发模式下的最大并发数
    """
    if mode == "concurrent":
        return ConcurrentToolExecutor(max_concurrent)
    elif mode == "clone":
        return SerialToolExecutor(clone_mode=True)
    else:
        return SerialToolExecutor(clone_mode=False)
