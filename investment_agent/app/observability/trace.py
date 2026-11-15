import json
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone

from ..db import get_db


_TRACE_INSERT_SQL = """
INSERT INTO trace_log (
    id, session_id, task_id, agent_name, step, event_type,
    detail, detail_size, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _safe_detail(detail: dict | None) -> str:
    """将 detail 字典序列化为 JSON 字符串"""
    if not detail:
        return "{}"
    return json.dumps(detail, ensure_ascii=False)


async def log_trace_batch(entries: Iterable[dict]) -> None:
    """批量记录 trace 事件，降低高频事件的 SQLite commit 次数。"""
    rows = []
    now = datetime.now(timezone.utc).isoformat()
    for entry in entries:
        detail_str = _safe_detail(entry.get("detail"))
        rows.append(
            (
                str(uuid.uuid4()),
                entry.get("session_id", ""),
                entry.get("task_id", ""),
                entry.get("agent_name"),
                entry.get("step"),
                entry.get("event_type", "unknown"),
                detail_str,
                len(detail_str),
                now,
            ),
        )

    if not rows:
        return

    async with get_db() as db:
        await db.executemany(_TRACE_INSERT_SQL, rows)
        await db.commit()


async def log_trace(
    session_id: str,
    task_id: str,
    step: int | None,
    event_type: str,
    detail: dict | None = None,
    agent_name: str | None = None,
) -> None:
    """记录单条 trace 事件。"""
    await log_trace_batch([
        {
            "session_id": session_id,
            "task_id": task_id,
            "step": step,
            "event_type": event_type,
            "detail": detail,
            "agent_name": agent_name,
        },
    ])
