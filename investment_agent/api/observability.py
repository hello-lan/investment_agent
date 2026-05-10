from fastapi import APIRouter

from ..db import get_db

router = APIRouter(prefix="/api/observability", tags=["observability"])


@router.get("/cost")
async def get_cost(session_id: str | None = None, task_id: str | None = None, limit: int = 100):
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
    where = []
    params: list = []
    if session_id:
        where.append("session_id = ?")
        params.append(session_id)
    if task_id:
        where.append("task_id = ?")
        params.append(task_id)

    sql = "SELECT * FROM trace_log"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(limit, 1000)))

    async with get_db() as db:
        cursor = await db.execute(sql, tuple(params))
        rows = await cursor.fetchall()

    return [dict(r) for r in rows]
