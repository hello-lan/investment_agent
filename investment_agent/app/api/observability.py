from fastapi import APIRouter

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
