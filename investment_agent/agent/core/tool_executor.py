"""工具执行器 + 死循环检测。

委派任务使用独立 token 预算的子引擎执行。
用户定义 Subagent 按挂载名拦截，支持同 turn 多个（串行执行）。
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
from .subagent_runtime import prepare_defined_subagent, run_defined_subagent

if TYPE_CHECKING:
    from .engine import AgentEngine

_log = logging.getLogger(__name__)


# ── 常量 ──────────────────────────────────────────────────────────────


# ── 死循环检测 ────────────────────────────────────────────────────────

class LoopDetector:
    """增强死循环检测：参数感知 + 振荡检测。"""

    _KEY_PARAMS: dict[str, list[str]] = {
        "run_command": ["command"],
        "run_python_script": ["script_path", "argv", "kwargs", "stdin"],
        "DelegateTask": ["task"],
        "Skill": ["name"],
        "list_files": ["path", "pattern", "recursive"],
        "read_file": ["path", "start_line"],
        "search_text": ["query", "path", "pattern"],
        "write_file": ["path"],
    }

    def __init__(self, threshold: int, whitelist: set[str]):
        self._threshold = threshold
        self._whitelist = whitelist
        self._recent: list[str] = []
        self._recent_params: list[str] = []
        self._detected_tool: str = ""
        self._detected_reason: str = ""

    @staticmethod
    def _hash_key_params(tool_name: str, input: dict) -> str:
        import hashlib, json
        key_fields = LoopDetector._KEY_PARAMS.get(tool_name)
        if key_fields is None:
            # 用户定义 Subagent 等：按 task 区分
            if "task" in input:
                key_fields = ["task"]
            else:
                key_fields = sorted(input.keys())
        key_params = {k: input.get(k) for k in key_fields if k in input}
        raw = json.dumps(key_params, sort_keys=True, ensure_ascii=False)
        return hashlib.md5(raw.encode()).hexdigest()[:8]

    def check(self, tool_calls: list[ToolCall]) -> bool:
        for tc in tool_calls:
            self._recent.append(tc.name)
            param_hash = self._hash_key_params(tc.name, tc.input)
            self._recent_params.append(f"{tc.name}:{param_hash}")

        max_keep = self._threshold * 3
        self._recent = self._recent[-max_keep:]
        self._recent_params = self._recent_params[-max_keep:]

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

        # 振荡检测按「工具名+关键参数」判断，避免多 skill 流水线误杀：
        # Skill(A)→list_files(A)→Skill(B)→list_files(B) 是正常编排，不是死循环。
        if len(candidates) >= 4:
            last4 = candidates[-4:]
            if (
                last4[0] == last4[2]
                and last4[1] == last4[3]
                and last4[0] != last4[1]
            ):
                a = last4[0].split(":")[0]
                b = last4[1].split(":")[0]
                self._detected_tool = f"{a} ↔ {b}"
                self._detected_reason = "oscillation"
                return True

        return False

    def error_event(self) -> dict:
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
    """统一的 DelegateTask 准备：深度检查 → 预算检查 → 技能过滤 → prompt 生成。"""
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

    parent_used = engine.total_input_tokens + engine.total_output_tokens
    if parent_used >= engine.token_budget:
        _log.warning(
            "[Delegate] 拒绝委派: 父预算已耗尽 used=%d/%d, task=%s",
            parent_used, engine.token_budget, task_desc,
        )
        return (
            f"错误：父 Agent token 预算已耗尽 ({parent_used}/{engine.token_budget})，"
            f"无法委派执行子任务"
        )

    from .subagent_config import resolve_subagent_runtime_config

    child_budget = resolve_subagent_runtime_config(engine, definition=None).token_budget
    if child_budget <= 0:
        _log.warning("[Delegate] 拒绝委派: 子预算未配置, task=%s", task_desc)
        return "错误：子Agent Token 预算未配置或为 0，无法委派执行子任务"

    raw_skill_names = tc.input.get("skill_names", []) or []
    from ..skills.loader import _registry as skill_registry
    parent_allowed = engine._allowed_skill_names
    skill_names = [
        n for n in raw_skill_names
        if skill_registry.get(n)
        and skill_registry[n].skill_type != SkillType.ORCH
        and n in parent_allowed
    ]

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
        "[Delegate] 委派就绪: id=%s, skills=%s, child_budget=%d, "
        "parent_used=%d/%d, depth=%d, task=%s",
        delegate_id, skill_names, child_budget,
        parent_used, engine.token_budget,
        engine.subagent_depth + 1, tc.input.get("task", "")[:100],
    )
    _log.debug("[Delegate] %s prompt: %s", delegate_id, prompt[:500])

    return skill_names, prompt, delegate_id


def _is_delegation_call(tc: ToolCall, engine) -> bool:
    if tc.name == "DelegateTask":
        return True
    mounted = getattr(engine, "_mounted_subagent_names", set()) or set()
    return tc.name in mounted


# ── 工具执行器 ─────────────────────────────────────────────────────────

class ToolExecutor:
    """工具执行器：串行执行工具列表；支持同 turn 多个用户定义 Subagent。"""

    async def execute(
        self, tool_calls: list[ToolCall], engine: "AgentEngine",
    ) -> AsyncGenerator[dict, None]:
        tool_results = []
        max_parallel = getattr(engine, "max_parallel_subagents", 3) or 3
        delegation_seen = 0

        for tc in tool_calls:
            yield {"type": EventType.TOOL_CALL, "tool": tc.name, "input": tc.input}
            t0 = time.monotonic()
            _delegate_id = None
            is_delegation = _is_delegation_call(tc, engine)

            if is_delegation:
                delegation_seen += 1
                if delegation_seen > max_parallel:
                    result = (
                        f"错误：同一步委派数已达上限 {max_parallel}，"
                        f"跳过 '{tc.name}'。请拆分到后续步骤或提高 max_parallel_subagents。"
                    )
                    _log.warning("[Delegate] %s", result)
                elif tc.name == "DelegateTask":
                    result = None
                    async for event in self._execute_delegate_task(engine, tc, t0):
                        if isinstance(event, _Value):
                            result, _delegate_id = event.value
                        else:
                            yield event
                else:
                    result = None
                    async for event in self._execute_defined_subagent(engine, tc, t0):
                        if isinstance(event, _Value):
                            result, _delegate_id = event.value
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
                "type": EventType.TOOL_RESULT,
                "tool": tc.name,
                "output": result,
                "duration_ms": duration_ms,
            }
            if is_delegation:
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

    @staticmethod
    async def _execute_delegate_task(
        engine: "AgentEngine", tc: ToolCall, t0: float,
    ) -> AsyncGenerator[dict, None]:
        prepared = await prepare_delegate_task(engine, tc)
        if isinstance(prepared, str):
            _log.info("[Delegate] 委派失败(prepare阶段): %s", prepared[:200])
            yield _Value((prepared, None))
            return

        skill_names, prompt, delegate_id = prepared
        billed_before = (
            getattr(engine, "billed_input_tokens", 0)
            + getattr(engine, "billed_output_tokens", 0)
        )
        _log.info("[Delegate] 开始执行: id=%s, skills=%s", delegate_id, skill_names)

        result = ""
        async for event in run_delegate_task(engine, skill_names, prompt, delegate_id):
            if event["type"] == EventType._DELEGATE_DONE:
                result = event["result"]
            elif event["type"] == EventType._DELEGATE_ERROR:
                result = f"子任务执行错误: {event['message']}"
            else:
                yield event

        billed_after = (
            getattr(engine, "billed_input_tokens", 0)
            + getattr(engine, "billed_output_tokens", 0)
        )
        _log.info(
            "[Delegate] 执行结束: id=%s, tokens_consumed=%d, result_len=%d, duration=%.1fs",
            delegate_id, billed_after - billed_before, len(result), time.monotonic() - t0,
        )
        yield _Value((result, delegate_id))

    @staticmethod
    async def _execute_defined_subagent(
        engine: "AgentEngine", tc: ToolCall, t0: float,
    ) -> AsyncGenerator[dict, None]:
        prepared = await prepare_defined_subagent(engine, tc.name, tc.input)
        if isinstance(prepared, str):
            _log.info("[Subagent] 执行失败(prepare阶段): %s", prepared[:200])
            yield _Value((prepared, None))
            return

        request, delegate_id = prepared
        billed_before = (
            getattr(engine, "billed_input_tokens", 0)
            + getattr(engine, "billed_output_tokens", 0)
        )
        _log.info(
            "[Subagent] 开始执行: id=%s name=%s",
            delegate_id, request.definition.get("name"),
        )

        result = ""
        async for event in run_defined_subagent(engine, request, delegate_id):
            if event["type"] == EventType._DELEGATE_DONE:
                result = event["result"]
            elif event["type"] == EventType._DELEGATE_ERROR:
                result = f"子任务执行错误: {event['message']}"
            else:
                yield event

        billed_after = (
            getattr(engine, "billed_input_tokens", 0)
            + getattr(engine, "billed_output_tokens", 0)
        )
        _log.info(
            "[Subagent] 执行结束: id=%s, tokens_consumed=%d, result_len=%d, duration=%.1fs",
            delegate_id, billed_after - billed_before, len(result), time.monotonic() - t0,
        )
        yield _Value((result, delegate_id))
