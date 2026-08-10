"""标准 Workflow 执行引擎：按 JSON / DAG 定义串行执行 ready 节点。"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import AsyncGenerator

from ..constants import EventType, SkillType
from ..workflows import WorkflowSpec, topological_order, validate_workflow_spec
from ._signals import _Value
from .base_loop import BaseLoopEngine
from .subagent import run_delegate_task
from .subagent_runtime import prepare_subagent_request, run_subagent
from .types import ToolCall


@dataclass
class WorkflowNodeState:
    """单个 workflow 节点的运行时状态。"""

    node_id: str
    status: str = "pending"
    output: str = ""
    error: str = ""
    step: int = 0


class WorkflowLoopEngine(BaseLoopEngine):
    """标准 workflow 执行器。"""

    WORKFLOW_RESULT_MAX_CHARS = 4000
    WORKFLOW_SUMMARY_MAX_CHARS = 500
    DELEGATE_MIN_REMAINING = 50_000

    async def run(self, messages: list[dict]) -> AsyncGenerator[dict, None]:
        """执行 workflow：加载定义 → 拓扑排序 → 串行执行节点 → 输出最终结果。"""
        if not self.provider:
            yield {"type": EventType.ERROR, "message": "No model provider configured."}
            return

        self._ensure_task_planner()
        messages = self.prepare_run(list(messages))
        self._messages = list(messages)

        try:
            workflow_row, spec = await self._load_workflow_spec()
        except Exception as exc:
            yield {"type": EventType.ERROR, "message": f"Workflow 加载失败: {exc}"}
            return

        order = topological_order(spec)
        node_map = {node.id: node for node in spec.nodes}
        states = {node.id: WorkflowNodeState(node_id=node.id) for node in spec.nodes}
        successors = self._build_successors(spec)
        workflow_name = workflow_row.get("name") or self.workflow_id or "workflow"
        workflow_messages = list(messages)
        user_goal = self._extract_user_goal(messages)

        yield {
            "type": EventType.WORKFLOW_START,
            "workflow_id": workflow_row.get("id"),
            "workflow_name": workflow_name,
            "node_count": len(spec.nodes),
            "step": 0,
        }

        step = 0
        for node_id in order:
            safety_result = self._safety.check(self, step, workflow_messages)
            if safety_result.stop_event:
                yield safety_result.stop_event
                return

            node = node_map[node_id]
            state = states[node_id]
            unresolved = [dep for dep in self._node_dependencies(node) if states[dep].status != "done"]
            if unresolved:
                message = f"Workflow 节点 {node.id} 存在未完成依赖: {', '.join(unresolved)}"
                yield {
                    "type": EventType.WORKFLOW_NODE_ERROR,
                    "workflow_id": workflow_row.get("id"),
                    "workflow_name": workflow_name,
                    "node_id": node.id,
                    "node_type": node.type,
                    "depends_on": node.depends_on,
                    "input_from": node.input_from,
                    "message": message,
                    "step": step,
                }
                yield {"type": EventType.ERROR, "message": message}
                return

            step += 1
            state.step = step
            self._messages = list(workflow_messages)
            yield {"type": EventType.STEP_START, "step": step}
            yield {
                "type": EventType.WORKFLOW_NODE_READY,
                "workflow_id": workflow_row.get("id"),
                "workflow_name": workflow_name,
                "node_id": node.id,
                "node_type": node.type,
                "depends_on": node.depends_on,
                "input_from": node.input_from,
                "step": step,
            }
            yield {
                "type": EventType.WORKFLOW_NODE_START,
                "workflow_id": workflow_row.get("id"),
                "workflow_name": workflow_name,
                "node_id": node.id,
                "node_type": node.type,
                "task": node.task,
                "depends_on": node.depends_on,
                "input_from": node.input_from,
                "step": step,
            }

            try:
                input_text = self._build_input_text(node, states)
                state.status = "running"
                result = ""

                if node.type == "assistant":
                    result = await self._run_assistant_node(node, user_goal, input_text)
                elif node.type == "delegate":
                    async for event in self._run_delegate_node(node, input_text, workflow_messages):
                        if isinstance(event, _Value):
                            result = event.value
                        else:
                            yield event
                elif node.type == "subagent":
                    async for event in self._run_subagent_node(node, input_text):
                        if isinstance(event, _Value):
                            result = event.value
                        else:
                            yield event
                else:
                    raise ValueError(f"不支持的 workflow 节点类型: {node.type}")

                state.status = "done"
                state.output = result.strip()
                workflow_messages.append({
                    "role": "user",
                    "content": self._build_result_message(node.id, state.output),
                })
                self._messages = list(workflow_messages)
                yield {
                    "type": EventType.WORKFLOW_NODE_DONE,
                    "workflow_id": workflow_row.get("id"),
                    "workflow_name": workflow_name,
                    "node_id": node.id,
                    "node_type": node.type,
                    "depends_on": node.depends_on,
                    "input_from": node.input_from,
                    "output_preview": self._preview_text(state.output, self.WORKFLOW_SUMMARY_MAX_CHARS),
                    "step": step,
                }
            except Exception as exc:
                state.status = "error"
                state.error = str(exc)
                yield {
                    "type": EventType.WORKFLOW_NODE_ERROR,
                    "workflow_id": workflow_row.get("id"),
                    "workflow_name": workflow_name,
                    "node_id": node.id,
                    "node_type": node.type,
                    "depends_on": node.depends_on,
                    "input_from": node.input_from,
                    "message": state.error,
                    "step": step,
                }
                yield {"type": EventType.ERROR, "message": f"Workflow 节点 {node.id} 执行失败: {state.error}"}
                return

        final_text = self._build_final_output(spec, states, successors)
        yield {
            "type": EventType.WORKFLOW_DONE,
            "workflow_id": workflow_row.get("id"),
            "workflow_name": workflow_name,
            "completed_nodes": len([s for s in states.values() if s.status == "done"]),
            "node_count": len(spec.nodes),
            "step": step,
        }
        if final_text:
            yield {"type": EventType.TEXT_DELTA, "content": final_text}
        yield self.build_done_event()

    async def _load_workflow_spec(self) -> tuple[dict, WorkflowSpec]:
        if not self.workflow_id:
            raise ValueError("workflow 模式缺少 workflow_id")
        if not self.storage:
            raise ValueError("workflow 模式未注入 storage")

        workflow_row = await self.storage.get_workflow_config(self.workflow_id)
        if not workflow_row:
            raise ValueError(f"workflow 不存在: {self.workflow_id}")

        raw_definition = workflow_row.get("definition") or "{}"
        if isinstance(raw_definition, str):
            try:
                definition = json.loads(raw_definition)
            except json.JSONDecodeError as exc:
                raise ValueError(f"workflow definition JSON 解析失败: {exc}") from exc
        else:
            definition = raw_definition

        spec = WorkflowSpec.model_validate(definition)
        validate_workflow_spec(spec)
        return workflow_row, spec

    @staticmethod
    def _node_dependencies(node) -> list[str]:
        return list(dict.fromkeys([*node.depends_on, *node.input_from]))

    @staticmethod
    def _build_successors(spec: WorkflowSpec) -> dict[str, list[str]]:
        successors = {node.id: [] for node in spec.nodes}
        for node in spec.nodes:
            for dep in set(node.depends_on) | set(node.input_from):
                successors.setdefault(dep, []).append(node.id)
        for node_id in successors:
            successors[node_id] = sorted(set(successors[node_id]))
        return successors

    def _extract_user_goal(self, messages: list[dict]) -> str:
        for message in messages:
            if message.get("role") == "user":
                text = self._extract_text_from_content(message.get("content", "")).strip()
                if text:
                    return text
        return "请根据 workflow 定义完成任务。"

    def _build_input_text(self, node, states: dict[str, WorkflowNodeState]) -> str:
        if not node.input_from:
            return ""
        parts = []
        for upstream_id in node.input_from:
            output = states[upstream_id].output.strip()
            if not output:
                continue
            parts.append(f"### 上游节点 {upstream_id}\n{output}")
        return "\n\n".join(parts)

    def _build_result_message(self, node_id: str, output: str) -> str:
        body = output.strip() or "(无文本输出)"
        body = self._preview_text(body, self.WORKFLOW_RESULT_MAX_CHARS)
        return f"[Workflow 节点结果] {node_id}\n{body}"

    def _build_final_output(
        self,
        spec: WorkflowSpec,
        states: dict[str, WorkflowNodeState],
        successors: dict[str, list[str]],
    ) -> str:
        sink_ids = [node.id for node in spec.nodes if not successors.get(node.id)]
        if not sink_ids:
            sink_ids = [node.id for node in spec.nodes]

        parts = []
        for node_id in sink_ids:
            text = states[node_id].output.strip()
            if text:
                parts.append((node_id, text))

        if not parts:
            for node in spec.nodes:
                text = states[node.id].output.strip()
                if text:
                    parts.append((node.id, text))

        if not parts:
            return ""
        if len(parts) == 1:
            return parts[0][1]
        return "\n\n".join(f"## {node_id}\n\n{text}" for node_id, text in parts)

    def _build_assistant_prompt(self, node, user_goal: str, input_text: str) -> str:
        sections = [
            "你正在执行一个标准 Workflow 的 assistant 节点。",
            f"原始用户目标：\n{user_goal}",
            f"当前节点：{node.id} ({node.type})",
            f"节点任务：\n{node.task}",
        ]
        if input_text:
            sections.append(f"上游输入：\n{input_text}")
        sections.append("请直接完成当前节点任务并输出结果，不要调用任何工具，不要解释 workflow 本身。")
        return "\n\n".join(sections)

    async def _run_assistant_node(self, node, user_goal: str, input_text: str) -> str:
        prompt = self._build_assistant_prompt(node, user_goal, input_text)
        kwargs = {
            "messages": self.provider.convert_messages([
                {"role": "user", "content": prompt},
            ]),
            "system": self.system_prompt,
            "tools": None,
        }
        if self.temperature is not None:
            kwargs["temperature"] = self.temperature
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens

        response = await self.provider.chat(**kwargs)
        self.total_input_tokens += response.input_tokens
        self.total_output_tokens += response.output_tokens
        self.total_cache_read_tokens += response.cache_read_tokens
        self.total_cache_creation_tokens += response.cache_creation_tokens
        self._last_input_tokens = response.input_tokens
        self._llm_call_count += 1

        result = (response.content or "").strip()
        if not result and response.reasoning_content:
            result = response.reasoning_content.strip()
        return result or "(assistant 节点完成，无文本输出)"

    async def _run_delegate_node(
        self,
        node,
        input_text: str,
        workflow_messages: list[dict],
    ) -> AsyncGenerator[dict | _Value, None]:
        if self.subagent_depth >= self.max_subagent_depth:
            raise ValueError(f"已达到最大委派深度 {self.max_subagent_depth}，无法创建子Agent")

        remaining = self.token_budget - self.total_input_tokens - self.total_output_tokens
        if remaining < self.DELEGATE_MIN_REMAINING:
            raise ValueError(f"剩余 token 预算不足 ({remaining}/{self.token_budget})，无法委派执行子任务")

        from ..skills.loader import _registry as skill_registry

        raw_skill_names = node.skill_names or []
        parent_allowed = self._allowed_skill_names
        skill_names = [
            name for name in raw_skill_names
            if skill_registry.get(name)
            and skill_registry[name].skill_type != SkillType.ORCH
            and name in parent_allowed
        ]
        if raw_skill_names and not skill_names:
            available = ", ".join(sorted(parent_allowed)) or "(无)"
            raise ValueError(
                f"请求的技能 {raw_skill_names} 均不可用。当前可用技能: {available}。"
            )

        task_text = node.task.strip()
        if input_text:
            task_text += f"\n\n上游输入：\n{input_text}"

        prompt = await self.task_planner.generate(task_text, skill_names, workflow_messages)
        self.total_input_tokens += self.task_planner.total_input_tokens
        self.total_output_tokens += self.task_planner.total_output_tokens
        self.task_planner.total_input_tokens = 0
        self.task_planner.total_output_tokens = 0

        delegate_id = f"workflow_delegate_{uuid.uuid4().hex[:8]}"
        result = ""
        error_message = ""
        async for event in run_delegate_task(self, skill_names, prompt, delegate_id):
            if event["type"] == EventType._DELEGATE_DONE:
                result = event["result"]
            elif event["type"] == EventType._DELEGATE_ERROR:
                error_message = event["message"]
            else:
                yield event

        if error_message:
            raise ValueError(error_message)
        yield _Value((result or "(委派节点完成，无文本输出)").strip())

    async def _run_subagent_node(self, node, input_text: str) -> AsyncGenerator[dict | _Value, None]:
        task_text = node.task.strip()
        if input_text:
            task_text += f"\n\n上游输入：\n{input_text}"

        tc = ToolCall(
            id=f"workflow_subagent_{node.id}",
            name="Subagent",
            input={
                "task": task_text,
                "targets": node.targets,
                "expected_output": node.expected_output,
                "output_path": node.output_path,
            },
        )
        prepared = await prepare_subagent_request(self, tc)
        if isinstance(prepared, str):
            raise ValueError(prepared)

        request, delegate_id = prepared
        result = ""
        error_message = ""
        async for event in run_subagent(self, request, delegate_id):
            if event["type"] == EventType._DELEGATE_DONE:
                result = event["result"]
            elif event["type"] == EventType._DELEGATE_ERROR:
                error_message = event["message"]
            else:
                yield event

        if error_message:
            raise ValueError(error_message)
        yield _Value((result or "(子Agent 节点完成，无文本输出)").strip())

    @staticmethod
    def _preview_text(text: str, limit: int) -> str:
        text = (text or "").strip()
        if len(text) <= limit:
            return text
        return text[:limit] + "\n...[已截断]"
