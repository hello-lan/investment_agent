import uuid
from datetime import datetime

from db import get_db


def _estimate_cost_usd(input_tokens: int, output_tokens: int) -> float:
    return ((input_tokens * 3) + (output_tokens * 15)) / 1_000_000


async def log_cost(
    session_id: str,
    task_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    now = datetime.utcnow().isoformat()
    cost_usd = _estimate_cost_usd(input_tokens, output_tokens)
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO cost_log (
                id, session_id, task_id, model, input_tokens, output_tokens, cost_usd, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                session_id,
                task_id,
                model,
                int(input_tokens),
                int(output_tokens),
                float(cost_usd),
                now,
            ),
        )
        await db.commit()
