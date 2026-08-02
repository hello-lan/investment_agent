"""react_subagent loop 使用的安全子Agent运行时。"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncGenerator

from ..config import EngineConfig, SAFE_SUBAGENT_SYSTEM_PROMPT
from ..constants import EventType, LoopMode
from ..context.runtime_compressor import NoOpRuntimeCompressor
from ..tools.file_scope_policy import FileScopePolicy
from ..tools.list_files import ListFilesTool
from ..tools.read_file import ReadFileTool
from ..tools.search_text import SearchTextTool
from ..tools.write_file import WriteFileTool
from ...config import ROOT_DIR

_log = logging.getLogger(__name__)
_SUBAGENT_TYPE = "subagent"
_SUBAGENT_MIN_REMAINING = 20_000


@dataclass
class SubagentRequest:
    task: str
    targets: list[str]
    expected_output: str | None = None
    output_path: str | None = None


def _forward_event(event: dict, subagent_id: str, depth: int) -> dict | str | None:
    event_type = event.get("type", "")
    prefix = "sub_" * depth

    if event_type == EventType.DONE:
        return EventType.DONE
    if event_type == EventType.ERROR:
        return EventType.ERROR
    if event_type.startswith("sub_"):
        forwarded = dict(event)
        forwarded["type"] = f"sub_{event_type}"
        forwarded.setdefault("delegate_id", subagent_id)
        forwarded.setdefault("depth", depth)
        forwarded.setdefault("agent_type", _SUBAGENT_TYPE)
        return forwarded

    forwarded = dict(event)
    forwarded["type"] = f"{prefix}{event_type}"
    forwarded.setdefault("delegate_id", subagent_id)
    forwarded.setdefault("depth", depth)
    forwarded.setdefault("agent_type", _SUBAGENT_TYPE)
    return forwarded


def _sync_tokens_from(target, source) -> None:
    target.total_input_tokens += source.total_input_tokens
    target.total_output_tokens += source.total_output_tokens
    target.total_cache_read_tokens += source.total_cache_read_tokens
    target.total_cache_creation_tokens += source.total_cache_creation_tokens


def _build_user_prompt(
    request: SubagentRequest,
    scope: FileScopePolicy,
    planned_task: str,
) -> str:
    targets = "\n".join(f"- {scope._to_rel(path)}" for path in scope.read_targets)
    output_path = (
        scope._to_rel(scope.output_path)
        if scope.output_path else f"(未指定，默认写入 {scope._to_rel(scope.default_write_root)}/)"
    )
    expected_output = request.expected_output or "(未指定，请按任务需要组织输出)"
    return (
        f"任务说明：\n{planned_task}\n\n"
        f"允许读取的 targets：\n{targets}\n\n"
        f"期望输出：\n{expected_output}\n\n"
        f"授权输出路径：\n{output_path}\n"
    )


def _create_child_engine(parent, request: SubagentRequest, subagent_id: str):
    from .loop_factory import create_loop_engine

    workspace_root = (
        Path(ROOT_DIR)
        / parent.subagent_workspace_dir
        / parent.session_id
        / subagent_id
    )
    scope = FileScopePolicy.for_subagent(
        project_root=ROOT_DIR,
        targets=request.targets,
        workspace_root=workspace_root,
        output_path=request.output_path,
    )
    remaining_budget = max(
        0, parent.token_budget - parent.total_input_tokens - parent.total_output_tokens,
    )
    child_cfg = EngineConfig(
        max_steps=max(min(parent.max_steps, 40), 20),
        slow_think_interval=0,
        loop_mode=LoopMode.REACT_SUBAGENT,
        token_budget=remaining_budget,
        loop_detection_threshold=parent.loop_threshold,
        context_trim_token_threshold=0,
        max_subagent_depth=parent.max_subagent_depth,
        offload_threshold=parent.offload_threshold,
        offload_summary_strategy=parent.offload_summary_strategy,
        offload_summary_chars=parent.offload_summary_chars,
        planning_max_tokens=parent.planning_max_tokens,
        subagent_workspace_dir=parent.subagent_workspace_dir,
    )
    child = create_loop_engine(
        session_id=f"subagent_{subagent_id}",
        system_prompt=(
            SAFE_SUBAGENT_SYSTEM_PROMPT.format(
                ROOT_DIR=ROOT_DIR,
                WORKSPACE_ROOT=workspace_root,
            ) + scope.prompt_section()
        ),
        provider=parent.provider,
        temperature=parent.temperature,
        max_tokens=parent.max_tokens,
        config=child_cfg,
        runtime_compressor=NoOpRuntimeCompressor(),
        subagent_depth=parent.subagent_depth + 1,
    )
    child._interrupt = parent._interrupt

    for tool in (
        ListFilesTool(scope),
        ReadFileTool(scope),
        SearchTextTool(scope),
        WriteFileTool(scope),
    ):
        child.register_tool(tool.schema, tool.run)

    return child, scope


async def prepare_subagent_request(engine, tc) -> tuple[SubagentRequest, str] | str:
    task_desc = tc.input.get("task", "")[:200]
    if engine.subagent_depth >= engine.max_subagent_depth:
        return (
            f"错误：已达到最大委派深度 {engine.max_subagent_depth}，无法创建子Agent"
        )

    remaining = engine.token_budget - engine.total_input_tokens - engine.total_output_tokens
    if remaining < _SUBAGENT_MIN_REMAINING:
        return (
            f"错误：剩余 token 预算不足 ({remaining}/{engine.token_budget})，无法委派执行子任务"
        )

    targets = tc.input.get("targets") or []
    if not isinstance(targets, list) or not targets:
        return "错误：Subagent 需要至少一个 targets 路径。"

    request = SubagentRequest(
        task=tc.input.get("task", ""),
        targets=[str(t) for t in targets if str(t).strip()],
        expected_output=tc.input.get("expected_output"),
        output_path=tc.input.get("output_path"),
    )
    if not request.task.strip():
        return "错误：Subagent 的 task 不能为空。"

    subagent_id = f"subagent_{uuid.uuid4().hex[:8]}"
    _log.info(
        "[Subagent] 准备完成: id=%s, remaining=%d/%d, depth=%d, task=%s",
        subagent_id,
        remaining,
        engine.token_budget,
        engine.subagent_depth + 1,
        task_desc,
    )
    return request, subagent_id


async def run_subagent(parent, request: SubagentRequest, subagent_id: str) -> AsyncGenerator[dict, None]:
    child, scope = _create_child_engine(parent, request, subagent_id)
    planned_task = request.task
    try:
        planner = parent._ensure_task_planner()
        planned_task = await planner.generate_subagent_task(
            request.task,
            request.targets,
            request.expected_output,
            request.output_path,
            parent._messages,
        )
        parent.total_input_tokens += planner.total_input_tokens
        parent.total_output_tokens += planner.total_output_tokens
        planner.total_input_tokens = 0
        planner.total_output_tokens = 0
    except Exception:
        _log.warning("Subagent task planning failed, fallback to raw task", exc_info=True)

    user_prompt = _build_user_prompt(request, scope, planned_task)
    child_messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": user_prompt, "cache_control": {"type": "ephemeral"}}
        ],
    }]
    depth = parent.subagent_depth + 1

    result_text = ""
    try:
        async for event in child.run(child_messages):
            forwarded = _forward_event(event, subagent_id, depth)
            if forwarded == EventType.DONE:
                break
            if forwarded == EventType.ERROR:
                _sync_tokens_from(parent, child)
                yield {"type": EventType._DELEGATE_ERROR, "message": event.get("message", "")}
                return
            if forwarded is not None:
                if forwarded["type"].endswith("text_delta"):
                    result_text += event.get("content", "")
                yield forwarded
    except Exception as e:
        _sync_tokens_from(parent, child)
        _log.error("[Subagent:%s] 异常终止: %s", subagent_id, e, exc_info=True)
        yield {"type": EventType._DELEGATE_ERROR, "message": str(e)}
        return

    _sync_tokens_from(parent, child)
    yield {
        "type": EventType._DELEGATE_DONE,
        "result": result_text.strip() or "(子Agent完成，无文本输出)",
    }
