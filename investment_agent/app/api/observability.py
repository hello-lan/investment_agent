from fastapi import APIRouter, Query

from ..db import get_db

router = APIRouter(prefix="/api/observability", tags=["observability"])


@router.get("/cost")
async def get_cost(session_id: str | None = None, task_id: str | None = None, limit: int = 100):
    """查询 Token 成本日志，支持按 session_id / task_id 过滤"""
    where = []
    params: list = []
    if session_id:
        where.append("session_id = ?")
        params.append(session_id)
    if task_id:
        where.append("task_id = ?")
        params.append(task_id)

    sql = "SELECT * FROM cost_log"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(limit, 500)))

    async with get_db() as db:
        cursor = await db.execute(sql, tuple(params))
        rows = await cursor.fetchall()

    return [dict(r) for r in rows]


@router.get("/traces")
async def get_traces(session_id: str | None = None, task_id: str | None = None, limit: int = 200):
    """查询执行链路追踪日志，LEFT JOIN 成本日志获取 model/token 信息"""
    where = []
    params: list = []
    if session_id:
        where.append("t.session_id = ?")
        params.append(session_id)
    if task_id:
        where.append("t.task_id = ?")
        params.append(task_id)

    sql = """SELECT t.*, c.model, c.input_tokens, c.output_tokens
FROM trace_log t
LEFT JOIN cost_log c ON t.session_id = c.session_id AND t.task_id = c.task_id"""
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY t.created_at DESC LIMIT ?"
    params.append(max(1, min(limit, 1000)))

    async with get_db() as db:
        cursor = await db.execute(sql, tuple(params))
        rows = await cursor.fetchall()

    return [dict(r) for r in rows]


@router.get("/sessions")
async def get_sessions(
    session_id: str | None = Query(None, description="指定 session_id 获取该会话的任务详情"),
    limit: int = 200,
):
    """会话级 Token 聚合或单会话任务详情。

    - 无 session_id：按会话聚合，返回每个会话的任务数、Token 总量、费用、时间范围和模型列表。
    - 有 session_id：返回该会话下每个任务的成本详情，附带 context_budget 信息。
    """
    clamp = max(1, min(limit, 500))

    async with get_db() as db:

        if session_id:
            sql = """SELECT
                c.*,
                (SELECT t.detail FROM trace_log t
                 WHERE t.session_id = c.session_id
                   AND t.task_id = c.task_id
                   AND t.event_type = 'context_budget'
                 LIMIT 1) AS context_budget
            FROM cost_log c
            WHERE c.session_id = ?
            ORDER BY c.created_at DESC
            LIMIT ?"""
            cursor = await db.execute(sql, (session_id, clamp))
            rows = await cursor.fetchall()
            results = [dict(r) for r in rows]
            for row in results:
                if row.get("cost_usd") is not None:
                    row["cost_usd"] = round(row["cost_usd"], 6)
            return results

        sql = """SELECT
            session_id,
            COUNT(DISTINCT task_id) AS task_count,
            SUM(input_tokens) AS total_input_tokens,
            SUM(output_tokens) AS total_output_tokens,
            SUM(cost_usd) AS total_cost_usd,
            MIN(created_at) AS first_seen,
            MAX(created_at) AS last_seen,
            GROUP_CONCAT(DISTINCT model) AS models
        FROM cost_log
        GROUP BY session_id
        ORDER BY last_seen DESC
        LIMIT ?"""
        cursor = await db.execute(sql, (clamp,))
        rows = await cursor.fetchall()
        results = [dict(r) for r in rows]
        for row in results:
            if row.get("total_cost_usd") is not None:
                row["total_cost_usd"] = round(row["total_cost_usd"], 6)
        return results
