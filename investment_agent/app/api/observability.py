import time

from fastapi import APIRouter, Query, HTTPException

from ..db import get_db

router = APIRouter(prefix="/api/observability", tags=["observability"])

# ── /sessions 聚合查询缓存（避免每 5 秒做一次全表 GROUP BY） ──────────────
_sessions_cache: dict = {
    "time": 0.0,
    "data": None,
}
_SESSIONS_CACHE_TTL = 30  # 秒


def _invalidate_sessions_cache() -> None:
    """标记缓存过期，下次请求会重新查询"""
    _sessions_cache["time"] = 0.0
    _sessions_cache["data"] = None


# ── /cost ───────────────────────────────────────────────────────────────────


@router.get("/cost")
async def get_cost(
    session_id: str | None = None,
    task_id: str | None = None,
    since: str | None = None,
    limit: int = 100,
):
    """查询 Token 成本日志，支持按 session_id / task_id 过滤"""
    where = []
    params: list = []
    if session_id:
        where.append("session_id = ?")
        params.append(session_id)
    if task_id:
        where.append("task_id = ?")
        params.append(task_id)
    if since:
        where.append("created_at >= ?")
        params.append(since)

    sql = "SELECT * FROM cost_log"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(max(1, min(limit, 500)))

    async with get_db() as db:
        cursor = await db.execute(sql, tuple(params))
        rows = await cursor.fetchall()

    return [dict(r) for r in rows]


# ── /traces 列表（截断 detail，减少传输量） ─────────────────────────────────

# detail 截断阈值：超过此长度的 detail 会被截断，前端按需加载完整内容
_DETAIL_TRUNCATE_LIMIT = 1000


@router.get("/traces")
async def get_traces(
    session_id: str | None = None,
    task_id: str | None = None,
    since: str | None = None,
    limit: int = 200,
):
    """查询执行链路追踪日志。

    为减少响应体积，detail 字段超过 1000 字符时会被截断，
    同时返回 detail_size（完整大小）供前端判断是否需要按需加载。
    """
    where = []
    params: list = []
    if session_id:
        where.append("t.session_id = ?")
        params.append(session_id)
    if task_id:
        where.append("t.task_id = ?")
        params.append(task_id)
    if since:
        where.append("t.created_at >= ?")
        params.append(since)

    # 指定 session_id 时允许获取全部日志，否则最多 1000 条
    max_limit = 10000 if session_id else 1000
    clamp = max(1, min(limit, max_limit))

    sql = f"""SELECT
        t.id, t.session_id, t.task_id, t.agent_name, t.step,
        t.event_type, t.created_at,
        CASE
            WHEN t.detail_size <= {_DETAIL_TRUNCATE_LIMIT} THEN t.detail
            ELSE SUBSTR(t.detail, 1, {_DETAIL_TRUNCATE_LIMIT})
        END AS detail,
        COALESCE(t.detail_size, LENGTH(t.detail)) AS detail_size,
        c.model, c.input_tokens, c.output_tokens
    FROM trace_log t
    LEFT JOIN cost_log c ON t.session_id = c.session_id AND t.task_id = c.task_id"""
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY t.created_at DESC LIMIT ?"
    params.append(clamp)

    async with get_db() as db:
        cursor = await db.execute(sql, tuple(params))
        rows = await cursor.fetchall()

    return [dict(r) for r in rows]


# ── /traces/{trace_id}（按需加载完整 detail） ──────────────────────────────


@router.get("/traces/{trace_id}")
async def get_trace_detail(trace_id: str):
    """获取单条 trace 的完整 detail，用于前端展开大消息时按需加载"""
    sql = """SELECT
        t.id, t.session_id, t.task_id, t.agent_name, t.step,
        t.event_type, t.detail,
        COALESCE(t.detail_size, LENGTH(t.detail)) AS detail_size,
        t.created_at,
        c.model, c.input_tokens, c.output_tokens
    FROM trace_log t
    LEFT JOIN cost_log c ON t.session_id = c.session_id AND t.task_id = c.task_id
    WHERE t.id = ?"""

    async with get_db() as db:
        cursor = await db.execute(sql, (trace_id,))
        row = await cursor.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="trace not found")
    return dict(row)


# ── /trace-sessions（链路日志的会话列表，分页） ─────────────────────────────


@router.get("/trace-sessions")
async def get_trace_sessions(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=50, description="每页条数"),
):
    """从 trace_log 获取去重的 session_id 列表（分页）。

    返回每个 session 的任务数、事件数、agent 名称和时间范围，
    用于链路日志页面的会话侧边栏。
    """
    offset = (page - 1) * page_size

    async with get_db() as db:
        # 总数
        count_cursor = await db.execute(
            "SELECT COUNT(DISTINCT session_id) AS cnt FROM trace_log"
        )
        total = (await count_cursor.fetchone())["cnt"]

        # 分页查询
        sql = """SELECT
            session_id,
            MIN(agent_name) AS agent_name,
            COUNT(DISTINCT task_id) AS task_count,
            COUNT(*) AS event_count,
            MIN(created_at) AS first_seen,
            MAX(created_at) AS last_seen
        FROM trace_log
        GROUP BY session_id
        ORDER BY last_seen DESC
        LIMIT ? OFFSET ?"""
        cursor = await db.execute(sql, (page_size, offset))
        rows = await cursor.fetchall()

    return {
        "items": [dict(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }


# ── /sessions（聚合查询带缓存） ────────────────────────────────────────────


@router.get("/sessions")
async def get_sessions(
    session_id: str | None = Query(None, description="指定 session_id 获取该会话的任务详情"),
    limit: int = 200,
):
    """会话级 Token 聚合或单会话任务详情。

    - 无 session_id：按会话聚合，返回每个会话的任务数、Token 总量、费用、时间范围和模型列表。
      结果缓存 30 秒，避免高频全表 GROUP BY。
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

        # 聚合查询：优先使用缓存
        now = time.monotonic()
        if _sessions_cache["data"] is not None and (now - _sessions_cache["time"]) < _SESSIONS_CACHE_TTL:
            return _sessions_cache["data"]

        sql = """SELECT
            session_id,
            MIN(agent_name) AS agent_name,
            MIN(currency) AS currency,
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

        _sessions_cache["data"] = results
        _sessions_cache["time"] = now
        return results


# ── /cleanup（手动触发数据归档） ───────────────────────────────────────────


@router.post("/cleanup")
async def trigger_cleanup(
    trace_days: int = Query(30, description="trace_log 保留天数"),
    cost_days: int = Query(90, description="cost_log 保留天数"),
):
    """手动触发过期数据清理，返回各表删除行数"""
    from ..db import cleanup_old_records

    result = await cleanup_old_records(trace_days=trace_days, cost_days=cost_days)
    _invalidate_sessions_cache()
    return result
