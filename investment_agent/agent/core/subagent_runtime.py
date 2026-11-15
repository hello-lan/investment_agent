"""用户定义 Subagent 运行时（TaskTool 语义）。

主 Agent 挂载的每个定义暴露为独立工具；调用时创建隔离子引擎，
仅以委托 task 为起点，最终摘要回主对话。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import AsyncGenerator

from ..config import EngineConfig
from ..constants import EventType, LoopMode
from ..context.runtime_compressor import NoOpRuntimeCompressor
from ...config import ROOT_DIR

_log = logging.getLogger(__name__)
_SUBAGENT_TYPE = "subagent"
_DEFAULT_SUBAGENT_TOKEN_BUDGET = 100_000


@dataclass
class DefinedSubagentRequest:
    definition: dict
    task: str
    expected_output: str | None = None


def build_subagent_tool_schema(definition: dict) -> dict:
    """将用户定义转为 Anthropic tool schema。"""
    return {
        "name": definition["name"],
        "description": definition.get("description") or f"委派给子Agent {definition['name']}",
        "input_schema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "交给该子Agent的完整委托说明，须自包含。",
                },
                "expected_output": {
                    "type": "string",
                    "description": "期望返回的结果形式（可选）。",
                },
            },
            "required": ["task"],
        },
    }


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
    """将子引擎用量记入父引擎的 billed_*（费用统计），不占用父 token_budget。"""
    target.billed_input_tokens = getattr(target, "billed_input_tokens", 0) + source.total_input_tokens
    target.billed_output_tokens = getattr(target, "billed_output_tokens", 0) + source.total_output_tokens
    # 子引擎自身也可能带有再委派的 billed_*
    target.billed_input_tokens += getattr(source, "billed_input_tokens", 0)
    target.billed_output_tokens += getattr(source, "billed_output_tokens", 0)
    target.total_cache_read_tokens += source.total_cache_read_tokens
    target.total_cache_creation_tokens += source.total_cache_creation_tokens


def _build_user_prompt(request: DefinedSubagentRequest) -> str:
    parts = [f"任务说明：\n{request.task.strip()}"]
    if request.expected_output and request.expected_output.strip():
        parts.append(f"期望输出：\n{request.expected_output.strip()}")
    return "\n\n".join(parts)


def _create_child_engine(parent, request: DefinedSubagentRequest, subagent_id: str):
    from .loop_factory import create_loop_engine
    from ..skills.dependency import expand_with_dependencies
    from ..skills.filtered_runner import make_filtered_skill_runner
    from ..skills.loader import _registry as skill_registry
    from ..tools.access_policy import AccessPolicy
    from ..tools.file_scope_policy import FileScopePolicy
    from ..tools.list_files import ListFilesTool
    from ..tools.read_file import ReadFileTool
    from ..tools.run_command import RunCommandTool
    from ..tools.search_text import SearchTextTool
    from ..tools.skill_tool import SkillTool
    from ..tools.write_file import WriteFileTool

    definition = request.definition
    child_budget = (
        getattr(parent, "subagent_token_budget", None) or _DEFAULT_SUBAGENT_TOKEN_BUDGET
    )
    child_cfg = EngineConfig(
        max_steps=max(min(parent.max_steps, 40), 20),
        slow_think_interval=0,
        loop_mode=LoopMode.REACT,
        token_budget=child_budget,
        subagent_token_budget=child_budget,
        loop_detection_threshold=parent.loop_threshold,
        runtime_context_compression_enabled=False,
        context_trim_token_threshold=0,
        max_subagent_depth=parent.max_subagent_depth,
        max_parallel_subagents=getattr(parent, "max_parallel_subagents", 3),
        offload_threshold=parent.offload_threshold,
        offload_summary_strategy=parent.offload_summary_strategy,
        offload_summary_chars=parent.offload_summary_chars,
        planning_max_tokens=parent.planning_max_tokens,
        subagent_workspace_dir=parent.subagent_workspace_dir,
    )

    system_prompt = (definition.get("system_prompt") or "").strip()
    system_prompt += (
        f"\n\n## 项目路径\n"
        f"ROOT_DIR = {ROOT_DIR}\n"
        f"你是叶子执行者：不要尝试再次委派或调用 DelegateTask。\n"
    )

    child_provider = definition.get("_provider") or parent.provider
    child = create_loop_engine(
        session_id=f"subagent_{subagent_id}",
        system_prompt=system_prompt,
        provider=child_provider,
        temperature=parent.temperature,
        max_tokens=parent.max_tokens,
        config=child_cfg,
        runtime_compressor=NoOpRuntimeCompressor(),
        subagent_depth=parent.subagent_depth + 1,
    )
    child._interrupt = parent._interrupt
    child._mounted_subagent_names = set()  # 禁止嵌套用户定义 Subagent

    skill_names = list(definition.get("skills") or [])
    all_skill_names = expand_with_dependencies(skill_names) if skill_names else []
    tool_names = set(definition.get("tools") or [])
    # 永不给子引擎委派类工具
    tool_names -= {"DelegateTask", "Subagent"}
    tool_names |= {"list_files", "read_file", "search_text", "write_file"}

    scope = FileScopePolicy.for_main_agent(skill_names=all_skill_names)
    child._system_prompt += scope.main_agent_prompt_section()
    for tool in (
        ListFilesTool(scope),
        ReadFileTool(scope),
        SearchTextTool(scope),
        WriteFileTool(scope),
    ):
        if tool.name in tool_names:
            child.register_tool(tool.schema, tool.run)
            tool_names.discard(tool.name)

    if "run_command" in tool_names:
        run_tool = RunCommandTool()
        policy = AccessPolicy.for_agent(str(ROOT_DIR), all_skill_names)
        run_tool.access_policy = policy
        child._system_prompt += policy.prompt_section()
        child.register_tool(run_tool.schema, run_tool.run)
        tool_names.discard("run_command")

    if skill_names:
        skill_tool = SkillTool()
        filtered_run = make_filtered_skill_runner(set(all_skill_names), skill_tool.run)
        child.register_tool(skill_tool.schema, filtered_run)
        child._allowed_skill_names = set(all_skill_names)
        for name in skill_names:
            skill = skill_registry.get(name)
            if skill:
                child.register_skill(skill)
                if skill.body:
                    # 优先保留文首 Quick start / 推荐命令，避免子 Agent 再通读脚本烧 token
                    body_excerpt = skill.body[:4500]
                    child._system_prompt += (
                        f"\n\n---\n\n# 技能 {name} 快速参考\n\n{body_excerpt}\n\n"
                        "执行约定：命令已在项目根（Windows/Linux）；"
                        "用相对路径+`/`直接跑脚本；不要 `cd`；不要通读 scripts/*.py。\n"
                        "已注入快速参考：第一步直接 `run_command` 跑脚本；"
                        "禁止先调 Skill / 禁止用 grep·read 扫年报替代脚本；"
                        "上游 task 的简化 schema 一律忽略，以脚本 Output contract 为准。\n"
                    )
                    if len(skill.body) > 4500:
                        child._system_prompt += (
                            f"> 以上为摘要。仅当脚本失败时再调用 Skill(name=\"{name}\")\n"
                        )
                    else:
                        child._system_prompt += (
                            f"> 完整说明已注入。不要再调用 Skill(name=\"{name}\")。\n"
                        )

    # 忽略剩余未知工具名
    if tool_names - {"Skill"}:
        _log.warning(
            "[Subagent] 未注册的工具被忽略: %s",
            sorted(tool_names - {"Skill"}),
        )

    return child


async def prepare_defined_subagent(
    engine, tool_name: str, tc_input: dict,
) -> tuple[DefinedSubagentRequest, str] | str:
    """准备用户定义 Subagent 请求；失败返回错误字符串。"""
    definitions = getattr(engine, "_mounted_subagents_by_name", {}) or {}
    definition = definitions.get(tool_name)
    if not definition:
        return f"错误：未挂载名为 '{tool_name}' 的 Subagent"

    if engine.subagent_depth >= engine.max_subagent_depth:
        return (
            f"错误：已达到最大委派深度 {engine.max_subagent_depth}，无法创建子Agent"
        )

    parent_used = engine.total_input_tokens + engine.total_output_tokens
    if parent_used >= engine.token_budget:
        return (
            f"错误：父 Agent token 预算已耗尽 ({parent_used}/{engine.token_budget})，"
            f"无法委派执行子任务"
        )

    child_budget = getattr(engine, "subagent_token_budget", None) or _DEFAULT_SUBAGENT_TOKEN_BUDGET
    if child_budget <= 0:
        return "错误：子Agent Token 预算未配置或为 0，无法委派执行子任务"

    task = (tc_input.get("task") or "").strip()
    if not task:
        return "错误：Subagent 的 task 不能为空。"

    request = DefinedSubagentRequest(
        definition=definition,
        task=task,
        expected_output=tc_input.get("expected_output"),
    )
    subagent_id = f"subagent_{uuid.uuid4().hex[:8]}"
    _log.info(
        "[Subagent] 准备完成: id=%s name=%s child_budget=%d parent_used=%d/%d depth=%d task=%s",
        subagent_id, tool_name, child_budget, parent_used, engine.token_budget,
        engine.subagent_depth + 1, task[:100],
    )
    return request, subagent_id


async def run_defined_subagent(
    parent, request: DefinedSubagentRequest, subagent_id: str,
) -> AsyncGenerator[dict, None]:
    child = _create_child_engine(parent, request, subagent_id)
    user_prompt = _build_user_prompt(request)
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


# ── 兼容旧名（workflow / 旧调用点迁移期）────────────────────────────

async def prepare_subagent_request(engine, tc) -> tuple[DefinedSubagentRequest, str] | str:
    """兼容入口：若 tc 带 definition/subagent_name 则走定义路径。"""
    name = tc.input.get("subagent_name") or tc.name
    return await prepare_defined_subagent(engine, name, tc.input)


async def run_subagent(parent, request, subagent_id: str) -> AsyncGenerator[dict, None]:
    if isinstance(request, DefinedSubagentRequest):
        async for event in run_defined_subagent(parent, request, subagent_id):
            yield event
        return
    yield {
        "type": EventType._DELEGATE_ERROR,
        "message": "旧版安全文件 Subagent 已移除，请改用用户定义 Subagent",
    }
