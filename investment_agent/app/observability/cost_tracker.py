import uuid
from datetime import datetime

from ..db import get_db


def _estimate_cost_usd(input_tokens: int, output_tokens: int) -> float:
    """估算 Token 成本（USD）：$3/M input + $15/M output（Claude Sonnet 定价参考）"""
    return ((input_tokens * 3) + (output_tokens * 15)) / 1_000_000


async def log_cost(
    session_id: str,
    task_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """任务结束时记录 Token 用量和预估成本到 cost_log 表"""
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
