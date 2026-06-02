import uuid
from datetime import datetime, timezone

from ..db import get_db


def _estimate_cost_usd(input_tokens: int, output_tokens: int,
                       cache_read_tokens: int = 0,
                       cache_creation_tokens: int = 0,
                       input_price: float | None = None,
                       output_price: float | None = None,
                       cache_read_price: float | None = None) -> float | None:
    """按模型配置的每百万 token 价格估算成本，未配置则返回 None。

    Anthropic cache_read 价格为 input_price 的 10%，cache_creation 为 input_price 的 125%。
    """
    if input_price is None or output_price is None:
        return None
    if cache_read_price is None:
        cache_read_price = input_price * 0.10
    return (
        (cache_read_tokens * cache_read_price)
        + (cache_creation_tokens * input_price * 1.25)
        + (input_tokens * input_price)
        + (output_tokens * output_price)
    ) / 1_000_000


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
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> None:
    """任务结束时记录 Token 用量和预估成本到 cost_log 表"""
    now = datetime.now(timezone.utc).isoformat()
    cost_usd = _estimate_cost_usd(
        input_tokens, output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
        input_price=input_price,
        output_price=output_price,
    )
    cache_hit_ratio = 0.0
    if input_tokens + cache_read_tokens + cache_creation_tokens > 0:
        cache_hit_ratio = cache_read_tokens / (input_tokens + cache_read_tokens + cache_creation_tokens)
    async with get_db() as db:
        await db.execute(
            """
            INSERT INTO cost_log (
                id, session_id, task_id, model, agent_name, input_tokens, output_tokens,
                cache_read_tokens, cache_creation_tokens, cache_hit_ratio, cost_usd, currency, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                session_id,
                task_id,
                model,
                agent_name,
                int(input_tokens),
                int(output_tokens),
                int(cache_read_tokens),
                int(cache_creation_tokens),
                round(cache_hit_ratio, 4),
                cost_usd,
                currency,
                now,
            ),
        )
        await db.commit()
