"""Workflow JSON schema 定义。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class WorkflowNode(BaseModel):
    """单个 workflow 节点。"""

    id: str = Field(min_length=1)
    type: Literal["assistant", "delegate", "subagent"]
    task: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    input_from: list[str] = Field(default_factory=list)
    skill_names: list[str] = Field(default_factory=list)
    targets: list[str] = Field(default_factory=list)
    expected_output: str | None = None
    output_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("depends_on", "input_from", "skill_names", "targets")
    @classmethod
    def _dedupe_strings(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in value or []:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result


class WorkflowSpec(BaseModel):
    """标准 workflow 定义。"""

    version: str = "1.0"
    nodes: list[WorkflowNode] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("nodes")
    @classmethod
    def _validate_nodes_not_empty(cls, value: list[WorkflowNode]) -> list[WorkflowNode]:
        if not value:
            raise ValueError("workflow 至少需要一个节点")
        return value
