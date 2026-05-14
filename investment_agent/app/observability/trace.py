import json
import uuid
from datetime import datetime

from ..db import get_db


def _safe_detail(detail: dict | None) -> str:
    """将 detail 字典序列化为 JSON 字符串，截断到 2000 字符"""
    if not detail:
        return "{}"
    text = json.dumps(detail, ensure_ascii=False)
    return text[:2000]


async def log_trace(
    session_id: str,
    task_id: str,
    step: int | None,
    event_type: str,
    detail: dict | None = None,
    agent_name: str | None = None,
) -> None:
    """记录每一步的执行事件到 trace_log 表，用于链路追踪和调试"""
    now = datetime.utcnow().isoformat()
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO trace_log (
                id, session_id, task_id, agent_name, step, event_type, detail, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                session_id,
                task_id,
                agent_name,
                step,
                event_type,
                _safe_detail(detail),
                now,
            ),
        )
        await db.commit()
