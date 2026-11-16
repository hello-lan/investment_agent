import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Query, HTTPException
from fastapi.responses import Response

from ..db import get_db
from ..observability.message_trace import fold_messages

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
        json_extract(t.detail, '$.delegate_id') AS delegate_id,
        json_extract(t.detail, '$.label') AS label,
        json_extract(t.detail, '$.agent_type') AS agent_type,
        json_extract(t.detail, '$.depth') AS depth,
        json_extract(t.detail, '$.message_count') AS message_count,
        json_extract(t.detail, '$.added_count') AS added_count,
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
    result = dict(row)
    if "llm_request" in (result.get("event_type") or ""):
        folded = await _reconstruct_request_detail(result)
        result["detail"] = json.dumps(folded, ensure_ascii=False)
    return result


def _detail_delegate_id(detail) -> str:
    if isinstance(detail, dict):
        return detail.get("delegate_id") or ""
    return ""


async def _reconstruct_request_detail(row: dict) -> dict:
    """把同一对话流从早到晚折到当前这条，填回完整 messages。"""
    this_detail = _parse_detail_json(row.get("detail"))
    if not isinstance(this_detail, dict):
        return {"raw": this_detail}

    delegate_id = _detail_delegate_id(this_detail)
    sql = """SELECT id, detail
        FROM trace_log
        WHERE session_id = ? AND task_id = ? AND event_type = ?
        ORDER BY created_at ASC, id ASC"""
    async with get_db() as db:
        cursor = await db.execute(
            sql,
            (row.get("session_id"), row.get("task_id"), row.get("event_type")),
        )
        rows = await cursor.fetchall()

    prior: list[dict] = []
    current = this_detail
    for item in rows:
        parsed = _parse_detail_json(item["detail"])
        if not isinstance(parsed, dict):
            continue
        if _detail_delegate_id(parsed) != delegate_id:
            continue
        if item["id"] == row["id"]:
            current = parsed
            break
        prior.append(parsed)

    folded_before = fold_messages(prior)
    folded = fold_messages(prior + [current])
    out = dict(current)
    out["messages"] = folded
    out["message_count"] = len(folded)
    if current.get("kind") == "delta":
        out["added_count"] = len(current.get("messages") or [])
    elif current.get("kind") == "snapshot":
        out["added_count"] = len(current.get("messages") or [])
    else:
        out["added_count"] = max(0, len(folded) - len(folded_before))
    return out


# ── /export/traces（按会话导出完整链路日志 JSON） ───────────────────────────

# 无 kind 的旧版 llm_request 仍是整份累积，导出时每条对话流只留最长一条
def _is_legacy_request(item: dict) -> bool:
    et = item.get("event_type") or ""
    if "llm_request" not in et:
        return False
    detail = item.get("detail")
    if not isinstance(detail, dict):
        return True
    return detail.get("kind") not in ("snapshot", "delta")


def _is_incremental_request(item: dict) -> bool:
    et = item.get("event_type") or ""
    if "llm_request" not in et:
        return False
    detail = item.get("detail")
    return isinstance(detail, dict) and detail.get("kind") in ("snapshot", "delta")


def _parse_detail_json(detail: str | None):
    """尽量把 detail 解析为 JSON 对象，失败则保留原字符串。"""
    if detail is None or detail == "":
        return None
    try:
        return json.loads(detail)
    except (TypeError, json.JSONDecodeError):
        return detail


def _request_stream_key(item: dict) -> tuple:
    """同一对话流的去重键：父 Agent 按 task；子 Agent 再按 delegate_id。"""
    detail = item.get("detail")
    delegate_id = ""
    if isinstance(detail, dict):
        delegate_id = detail.get("delegate_id") or ""
    return (
        item.get("event_type") or "",
        item.get("task_id") or "",
        item.get("agent_name") or "",
        delegate_id,
    )


def _dedupe_legacy_requests(requests: list[dict]) -> tuple[list[dict], int]:
    """旧版累积型 request：每条对话流只保留 detail 最大的一条。"""
    best: dict[tuple, tuple[int, dict]] = {}
    for item in requests:
        size = int(item.get("detail_size") or 0)
        key = _request_stream_key(item)
        prev = best.get(key)
        if prev is None or size >= prev[0]:
            best[key] = (size, item)
    kept = [v[1] for v in best.values()]
    return kept, len(requests) - len(kept)


def _attach_folded_context(items: list[dict]) -> None:
    """对话流最后一条挂上折叠后的完整 messages，中间条保持增量。"""
    if not items:
        return
    folded = fold_messages([
        it["detail"] for it in items if isinstance(it.get("detail"), dict)
    ])
    last = items[-1]
    detail = dict(last.get("detail") or {})
    if detail.get("kind") == "delta":
        detail["delta_messages"] = detail.get("messages")
    detail["messages"] = folded
    detail["message_count"] = len(folded)
    detail["folded"] = True
    last["detail"] = detail


def _prepare_export_traces(traces: list[dict]) -> tuple[list[dict], int]:
    """旧数据去重；增量数据保留，并在每条流的最后一条放上完整上下文。"""
    others: list[dict] = []
    legacy: list[dict] = []
    incremental: dict[tuple, list[dict]] = {}

    for item in traces:
        if _is_incremental_request(item):
            incremental.setdefault(_request_stream_key(item), []).append(item)
        elif _is_legacy_request(item):
            legacy.append(item)
        else:
            others.append(item)

    kept_legacy, dropped = _dedupe_legacy_requests(legacy)
    incremental_out: list[dict] = []
    for items in incremental.values():
        _attach_folded_context(items)
        incremental_out.extend(items)

    merged = others + kept_legacy + incremental_out
    merged.sort(key=lambda x: (x.get("created_at") or "", x.get("id") or ""))
    return merged, dropped


@router.get("/export/traces")
async def export_traces(
    session_id: str = Query(..., description="要导出的会话 ID"),
):
    """导出指定会话的链路日志为 JSON（detail 不截断）。

    旧版 llm_request 仍按对话流只保留最长一条。增量记录全部保留，
    每条对话流的最后一条 messages 为折叠后的完整上下文。
    成本信息单独放在 costs 字段，避免 JOIN 到每条 trace 造成冗余。
    """
    trace_sql = """SELECT
        t.id, t.session_id, t.task_id, t.agent_name, t.step,
        t.event_type, t.detail,
        COALESCE(t.detail_size, LENGTH(t.detail)) AS detail_size,
        t.created_at
    FROM trace_log t
    WHERE t.session_id = ?
    ORDER BY t.created_at ASC"""

    cost_sql = """SELECT
        id, session_id, task_id, agent_name, model,
        input_tokens, output_tokens, cost_usd, currency, created_at
    FROM cost_log
    WHERE session_id = ?
    ORDER BY created_at ASC"""

    async with get_db() as db:
        cursor = await db.execute(trace_sql, (session_id,))
        rows = await cursor.fetchall()
        cost_cursor = await db.execute(cost_sql, (session_id,))
        cost_rows = await cost_cursor.fetchall()

    if not rows:
        raise HTTPException(status_code=404, detail="该会话暂无链路日志")

    raw_traces = []
    for r in rows:
        item = dict(r)
        item["detail"] = _parse_detail_json(item.get("detail"))
        raw_traces.append(item)

    traces, dropped_requests = _prepare_export_traces(raw_traces)
    costs = [dict(r) for r in cost_rows]

    payload = {
        "session_id": session_id,
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(traces),
        "count_before_dedupe": len(raw_traces),
        "dropped_cumulative_requests": dropped_requests,
        "dedupe_note": (
            "无 kind 的旧版 llm_request 仍按对话流只保留 detail 最大的一条。"
            "增量记录（kind=snapshot/delta）全部保留；"
            "每条对话流最后一条的 messages 是折叠后的完整上下文，"
            "若该条原为 delta，原增量在 delta_messages。"
        ),
        "costs": costs,
        "traces": traces,
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)[:48]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"trace_{safe_id}_{stamp}.json"

    return Response(
        content=content.encode("utf-8"),
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


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
