import uuid
from datetime import datetime

from ..db import get_db


def _estimate_cost_usd(input_tokens: int, output_tokens: int,
                       input_price: float | None = None,
                       output_price: float | None = None) -> float | None:
    """按模型配置的每百万 token 价格估算成本，未配置则返回 None"""
    if input_price is None or output_price is None:
        return None
    return ((input_tokens * input_price) + (output_tokens * output_price)) / 1_000_000


async def log_cost(
    session_id: str,
    task_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    agent_name: str | None = None,
    input_price: float | None = None,
    output_price: float | None = None,
    currency: str = "USD",
) -> None:
    """任务结束时记录 Token 用量和预估成本到 cost_log 表"""
    now = datetime.utcnow().isoformat()
    cost_usd = _estimate_cost_usd(input_tokens, output_tokens, input_price, output_price)
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO cost_log (
                id, session_id, task_id, model, agent_name, input_tokens, output_tokens, cost_usd, currency, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                session_id,
                task_id,
                model,
                agent_name,
                int(input_tokens),
                int(output_tokens),
                cost_usd,
                currency,
                now,
            ),
        )
        await db.commit()
