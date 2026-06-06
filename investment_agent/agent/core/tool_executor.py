"""工具执行器 + 死循环检测。

委派任务使用共享预算的子引擎执行（原 clone 模式）。
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import AsyncGenerator, TYPE_CHECKING

from ._signals import _Value
from ..constants import EventType, SkillType
from .provider import ToolCall
from .subagent import run_delegate_task

if TYPE_CHECKING:
    from .engine import AgentEngine

_log = logging.getLogger(__name__)


# ── 常量 ──────────────────────────────────────────────────────────────

DELEGATE_MIN_REMAINING = 50_000    # 委派模式最低剩余 token


# ── 死循环检测 ────────────────────────────────────────────────────────

class LoopDetector:
    """增强死循环检测：参数感知 + 振荡检测。

    检测规则：
    1. 相同工具 + 相同关键参数连续调用超过阈值 → 死循环
    2. 连续滑动窗口内呈现 A→B→A→B 振荡模式 → 策略混乱
    """

    # 各工具的关键参数（用于区分"不同参数的同名调用"）
    _KEY_PARAMS: dict[str, list[str]] = {
        "get_stock_info": ["symbol"],
        "get_stock_price": ["symbol", "period"],
        "get_income_statement": ["symbol", "report_type"],
        "get_balance_sheet": ["symbol", "report_type"],
        "get_cash_flow": ["symbol", "report_type"],
        "get_valuation": ["symbol"],
        "get_financial_indicators": ["symbol"],
        "run_command": ["command"],
        "DelegateTask": ["task"],
    }

    def __init__(self, threshold: int, whitelist: set[str]):
        self._threshold = threshold
        self._whitelist = whitelist
        self._recent: list[str] = []
        self._recent_params: list[str] = []  # 参数哈希，用于精确匹配
        self._detected_tool: str = ""
        self._detected_reason: str = ""  # "repeat" | "oscillation"

    @staticmethod
    def _hash_key_params(tool_name: str, input: dict) -> str:
        """提取关键参数并哈希，用于区分不同参数的同名工具调用。"""
        import hashlib, json
        key_fields = LoopDetector._KEY_PARAMS.get(tool_name, [])
        if not key_fields:
            # 未知工具：对所有参数排序后哈希
            key_fields = sorted(input.keys())
        key_params = {k: input.get(k) for k in key_fields if k in input}
        raw = json.dumps(key_params, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(raw.encode()).hexdigest()[:8]

    def check(self, tool_calls: list[ToolCall]) -> bool:
        """记录工具调用并检测死循环。返回 True 表示检测到。"""
        for tc in tool_calls:
            self._recent.append(tc.name)
            param_hash = self._hash_key_params(tc.name, tc.input)
            self._recent_params.append(f"{tc.name}:{param_hash}")

        # 保持滑动窗口（oscillation 检测需要两倍阈值保证覆盖两个周期）
        max_keep = self._threshold * 3
        self._recent = self._recent[-max_keep:]
        self._recent_params = self._recent_params[-max_keep:]

        # 检测 1: 相同工具+相同参数连续重复（参数感知）
        candidates = [
            p for p, n in zip(self._recent_params, self._recent)
            if n not in self._whitelist
        ]
        if len(candidates) >= self._threshold:
            tail = candidates[-self._threshold:]
            if len(set(tail)) == 1:
                self._detected_tool = tail[0].split(":")[0]
                self._detected_reason = "repeat"
                return True

        # 检测 2: 振荡模式 A→B→A→B（不区分参数，只看工具名切换）
        if len(self._recent) >= 6:
            tools = [n for n in self._recent if n not in self._whitelist]
            if len(tools) >= 4:
                last4 = tools[-4:]
                if last4[0] == last4[2] and last4[1] == last4[3] and last4[0] != last4[1]:
                    self._detected_tool = f"{last4[0]} ↔ {last4[1]}"
                    self._detected_reason = "oscillation"
                    return True

        return False

    def error_event(self) -> dict:
        """返回死循环错误事件。"""
        if self._detected_reason == "oscillation":
            return {
                "type": "error",
                "message": (
                    f"检测到工具振荡模式: {self._detected_tool}，"
                    f"策略可能陷入循环"
                ),
                "recent_tool_calls": list(self._recent),
            }
        return {
            "type": "error",
            "message": (
                f"死循环检测: '{self._detected_tool}' "
                f"使用相同参数连续调用 {self._threshold} 次"
            ),
            "recent_tool_calls": list(self._recent),
        }


# ── 委派任务准备 ──────────────────────────────────────────────────────

async def prepare_delegate_task(
    engine: "AgentEngine",
    tc: ToolCall,
) -> tuple[list[str], str, str] | str:
    """统一的 DelegateTask 准备：深度检查 → 预算检查 → 技能过滤 → prompt 生成。

    Args:
        engine: 父 AgentEngine 实例
        tc: DelegateTask 工具调用

    Returns:
        成功: (skill_names, prompt, delegate_id)
        失败: 错误信息字符串
    """
    task_desc = tc.input.get("task", "")[:200]

    if engine.subagent_depth >= engine.max_subagent_depth:
        _log.warning(
            "[Delegate] 拒绝委派: 已达最大深度 %d, task=%s",
            engine.max_subagent_depth, task_desc,
        )
        return (
            f"错误：已达到最大委派深度 {engine.max_subagent_depth}，"
            f"无法创建子Agent"
        )

    remaining = engine.token_budget - engine.total_input_tokens - engine.total_output_tokens
    if remaining < DELEGATE_MIN_REMAINING:
        _log.warning(
            "[Delegate] 拒绝委派: 预算不足 remaining=%d/%d, task=%s",
            remaining, engine.token_budget, task_desc,
        )
        return (
            f"错误：剩余 token 预算不足 ({remaining}/{engine.token_budget})，"
            f"无法委派执行子任务"
        )

    raw_skill_names = tc.input.get("skill_names", []) or []
    from ..skills.loader import _registry as skill_registry
    parent_allowed = engine._allowed_skill_names
    skill_names = [
        n for n in raw_skill_names
        if skill_registry.get(n)
        and skill_registry[n].skill_type != SkillType.ORCH
        and n in parent_allowed
    ]

    # 技能过滤日志：记录请求 vs 实际可用
    filtered_out = [n for n in raw_skill_names if n not in skill_names]
    if filtered_out:
        reasons = []
        for n in filtered_out:
            sk = skill_registry.get(n)
            if not sk:
                reasons.append(f"{n}(未注册)")
            elif sk.skill_type == "orch":
                reasons.append(f"{n}(orch技能不可委派)")
            elif n not in parent_allowed:
                reasons.append(f"{n}(不在父Agent允许列表)")
            else:
                reasons.append(f"{n}(未知原因)")
        _log.info(
            "[Delegate] 技能过滤: 请求=%s, 通过=%s, 过滤掉=%s",
            raw_skill_names, skill_names, ", ".join(reasons),
        )

    # 如果请求了技能但全部无效，返回错误而非静默创建无技能的子Agent
    if raw_skill_names and not skill_names:
        available = ", ".join(sorted(parent_allowed)) or "(无)"
        _log.warning(
            "[Delegate] 拒绝委派: 所有技能均不可用, 请求=%s, 可用=%s",
            raw_skill_names, available,
        )
        return (
            f"错误：请求的技能 {raw_skill_names} 均不可用。"
            f"当前可用技能: {available}。"
            f"请检查技能名称是否正确。"
        )

    prompt = await engine.task_planner.generate(task_desc, skill_names, engine._messages)
    delegate_id = f"delegate_{uuid.uuid4().hex[:8]}"

    _log.info(
        "[Delegate] 委派就绪: id=%s, skills=%s, budget_remaining=%d/%d, "
        "depth=%d, task=%s",
        delegate_id, skill_names, remaining, engine.token_budget,
        engine.subagent_depth + 1, tc.input.get("task", "")[:100],
    )
    _log.debug("[Delegate] %s prompt: %s", delegate_id, prompt[:500])

    return skill_names, prompt, delegate_id


# ── 工具执行器 ─────────────────────────────────────────────────────────


class ToolExecutor:
    """工具执行器：串行执行工具列表，委派任务使用共享预算的子引擎。

    DelegateTask 逐个执行，通过 run_delegate_task 在隔离子引擎中运行。
    非 DelegateTask 直接调用 engine 的 tool_handler。
    """

    async def execute(
        self, tool_calls: list[ToolCall], engine: "AgentEngine",
    ) -> AsyncGenerator[dict, None]:
        tool_results = []
        for tc in tool_calls:
            yield {"type": EventType.TOOL_CALL, "tool": tc.name, "input": tc.input}
            t0 = time.monotonic()

            if tc.name == "DelegateTask":
                result = None
                _delegate_id = None
                async for event in self._execute_delegate_task(engine, tc, t0):
                    if isinstance(event, _Value):
                        result, _delegate_id = event.value
                    else:
                        yield event
            else:
                _delegate_id = None
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
                "type": EventType.TOOL_RESULT,
                "tool": tc.name,
                "output": result,
                "duration_ms": duration_ms,
            }
            if tc.name == "DelegateTask":
                yield {
                    "type": EventType.BUDGET_STATUS,
                    "total_used": engine.total_input_tokens + engine.total_output_tokens,
                    "budget": engine.token_budget,
                    "remaining": engine.token_budget - engine.total_input_tokens - engine.total_output_tokens,
                    "delegate_id": _delegate_id,
                    "depth": engine.subagent_depth + 1,
                }
            tool_results.append({
                "type": EventType.TOOL_RESULT,
                "tool_use_id": tc.id,
                "content": result,
            })
        yield _Value(tool_results)

    # ── DelegateTask 拦截执行 ───────────────────────────────────────────

    @staticmethod
    async def _execute_delegate_task(
        engine: "AgentEngine", tc: ToolCall, t0: float,
    ) -> AsyncGenerator[dict, None]:
        """拦截 DelegateTask 调用：准备 → 创建子引擎 → 执行。

        将子Agent的执行事件转发给调用方，最后 yield _Value((result, delegate_id))。
        """
        prepared = await prepare_delegate_task(engine, tc)
        if isinstance(prepared, str):
            _log.info("[Delegate] 委派失败(prepare阶段): %s", prepared[:200])
            yield _Value((prepared, None))
            return

        skill_names, prompt, delegate_id = prepared
        tokens_before = engine.total_input_tokens + engine.total_output_tokens
        _log.info("[Delegate] 开始执行: id=%s, skills=%s", delegate_id, skill_names)

        result = ""
        async for event in run_delegate_task(engine, skill_names, prompt, delegate_id):
            if event["type"] == EventType._DELEGATE_DONE:
                result = event["result"]
            elif event["type"] == EventType._DELEGATE_ERROR:
                result = f"子任务执行错误: {event['message']}"
            else:
                yield event  # 转发子Agent事件到SSE流

        tokens_after = engine.total_input_tokens + engine.total_output_tokens
        _log.info(
            "[Delegate] 执行结束: id=%s, tokens_consumed=%d, "
            "result_len=%d, duration=%.1fs",
            delegate_id, tokens_after - tokens_before,
            len(result), time.monotonic() - t0,
        )
        yield _Value((result, delegate_id))
