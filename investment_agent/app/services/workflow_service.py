"""Workflow 配置服务层。"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from ...agent.workflows import WorkflowSpec, validate_workflow_spec
from ..db import get_db


class WorkflowService:
    """Workflow CRUD 与校验。"""

    @staticmethod
    def _normalize_definition(definition: dict | str) -> tuple[WorkflowSpec, str]:
        if isinstance(definition, str):
            try:
                raw = json.loads(definition)
            except json.JSONDecodeError as exc:
                raise ValueError(f"workflow JSON 解析失败: {exc}") from exc
        elif isinstance(definition, dict):
            raw = definition
        else:
            raise ValueError("workflow definition 必须是 JSON 对象")

        spec = WorkflowSpec.model_validate(raw)
        validate_workflow_spec(spec)
        return spec, json.dumps(spec.model_dump(mode="json"), ensure_ascii=False, indent=2)

    @staticmethod
    async def list_workflows() -> list[dict[str, Any]]:
        async with get_db() as db:
            cursor = await db.execute(
                "SELECT id, name, description, definition, created_at, updated_at FROM workflows ORDER BY updated_at DESC, created_at DESC"
            )
            rows = await cursor.fetchall()
        results = []
        for row in rows:
            item = dict(row)
            try:
                definition = json.loads(item["definition"])
                item["node_count"] = len(definition.get("nodes", []))
                item["version"] = definition.get("version")
            except Exception:
                item["node_count"] = 0
                item["version"] = None
            results.append(item)
        return results

    @staticmethod
    async def get_workflow(workflow_id: str) -> dict[str, Any] | None:
        async with get_db() as db:
            row = await db.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,))
            result = await row.fetchone()
        return dict(result) if result else None

    @staticmethod
    async def create_workflow(
        name: str,
        description: str = "",
        definition: dict | str | None = None,
    ) -> str:
        _, serialized = WorkflowService._normalize_definition(definition or {})
        workflow_id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()
        async with get_db() as db:
            await db.execute(
                "INSERT INTO workflows (id, name, description, definition, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                (workflow_id, name, description, serialized, now, now),
            )
            await db.commit()
        return workflow_id

    @staticmethod
    async def update_workflow(
        workflow_id: str,
        name: str,
        description: str = "",
        definition: dict | str | None = None,
    ) -> bool:
        _, serialized = WorkflowService._normalize_definition(definition or {})
        now = datetime.now(timezone.utc).isoformat()
        async with get_db() as db:
            row = await db.execute("SELECT id FROM workflows WHERE id = ?", (workflow_id,))
            if not await row.fetchone():
                return False
            await db.execute(
                "UPDATE workflows SET name = ?, description = ?, definition = ?, updated_at = ? WHERE id = ?",
                (name, description, serialized, now, workflow_id),
            )
            await db.commit()
        return True

    @staticmethod
    async def delete_workflow(workflow_id: str) -> None:
        async with get_db() as db:
            await db.execute("DELETE FROM workflows WHERE id = ?", (workflow_id,))
            await db.commit()

    @staticmethod
    async def validate_definition(definition: dict | str) -> dict[str, Any]:
        spec, serialized = WorkflowService._normalize_definition(definition)
        data = json.loads(serialized)
        return {
            "ok": True,
            "version": spec.version,
            "node_count": len(spec.nodes),
            "definition": data,
        }
