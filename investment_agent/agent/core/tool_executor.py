"""工具执行器 + 死循环检测。

用户定义 Subagent 按挂载名拦截，支持同 turn 多个（串行执行）；
子任务使用独立 token 预算。
"""

from __future__ import annotations

import logging
import time
from typing import AsyncGenerator, TYPE_CHECKING

from ._signals import _Value
from ..constants import EventType
from .provider import ToolCall
from .subagent_runtime import prepare_defined_subagent, run_defined_subagent

if TYPE_CHECKING:
    from .engine import AgentEngine

_log = logging.getLogger(__name__)


# ── 死循环检测 ────────────────────────────────────────────────────────

class LoopDetector:
    """增强死循环检测：参数感知 + 振荡检测。"""

    _KEY_PARAMS: dict[str, list[str]] = {
        "run_command": ["command"],
        "run_python_script": ["script_path", "argv", "kwargs", "stdin"],
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


def _is_delegation_call(tc: ToolCall, engine) -> bool:
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
