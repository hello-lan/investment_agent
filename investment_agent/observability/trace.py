import json
import uuid
from datetime import datetime

from ..db import get_db


def _safe_detail(detail: dict | None) -> str:
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
) -> None:
    now = datetime.utcnow().isoformat()
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO trace_log (
                id, session_id, task_id, step, event_type, detail, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                session_id,
                task_id,
                step,
                event_type,
                _safe_detail(detail),
                now,
            ),
        )
        await db.commit()
