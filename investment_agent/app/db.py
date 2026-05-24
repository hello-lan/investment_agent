import shutil

import aiosqlite
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from ..config import get_settings, PROJECT_ROOT


# SQLite 数据库文件路径
DB_PATH = (PROJECT_ROOT / get_settings().get("db", {}).get("sqlite_path", "./data/agent.db")).resolve()


@asynccontextmanager
async def get_db():
    """异步 SQLite 上下文管理器：自动开启/关闭连接，Row 工厂返回字典行"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


async def init_db() -> None:
    """初始化数据库：建表 + 执行旧结构迁移"""
    async with get_db() as db:
        await db.executescript("""
            -- LLM 模型配置（支持 Anthropic 和 OpenAI 兼容接口）
            CREATE TABLE IF NOT EXISTS models (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                type        TEXT NOT NULL,
                api_key     TEXT DEFAULT '',
                model       TEXT NOT NULL,
                base_url    TEXT DEFAULT '',
                is_default  INTEGER DEFAULT 0,
                input_price  REAL,
                output_price REAL,
                currency     TEXT DEFAULT 'USD',
                created_at  TEXT
            );

            -- 自定义 Agent 配置（绑定模型、Skills、压缩参数）
            CREATE TABLE IF NOT EXISTS agents (
                id            TEXT PRIMARY KEY,
                name          TEXT NOT NULL,
                description   TEXT,
                system_prompt TEXT,
                model_id      TEXT,
                temperature   REAL DEFAULT 0.7,
                max_tokens    INTEGER DEFAULT 4096,
                skills        TEXT DEFAULT '[]',
                compress_config TEXT,
                engine_config TEXT,
                created_at    TEXT,
                updated_at    TEXT
            );

            -- 对话会话
            CREATE TABLE IF NOT EXISTS sessions (
                id         TEXT PRIMARY KEY,
                agent_id   TEXT,
                title      TEXT,
                status     TEXT DEFAULT 'active',
                created_at TEXT
            );

            -- 会话消息（role/content/tool_calls/token_usage）
            CREATE TABLE IF NOT EXISTS messages (
                id          TEXT PRIMARY KEY,
                session_id  TEXT NOT NULL,
                role        TEXT NOT NULL,
                content     TEXT,
                tool_calls  TEXT,
                token_usage TEXT,
                created_at  TEXT
            );

            -- 断点续跑状态（Phase 2 启用）
            CREATE TABLE IF NOT EXISTS checkpoints (
                task_id    TEXT PRIMARY KEY,
                session_id TEXT,
                step       INTEGER DEFAULT 0,
                messages   TEXT,
                status     TEXT DEFAULT 'running',
                updated_at TEXT
            );

            -- Token 成本日志
            CREATE TABLE IF NOT EXISTS cost_log (
                id            TEXT PRIMARY KEY,
                session_id    TEXT,
                task_id       TEXT,
                model         TEXT,
                input_tokens  INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cost_usd      REAL DEFAULT 0,
                currency      TEXT,
                created_at    TEXT
            );

            -- 执行链路追踪日志
            CREATE TABLE IF NOT EXISTS trace_log (
                id         TEXT PRIMARY KEY,
                session_id TEXT,
                task_id    TEXT,
                agent_name TEXT,
                step       INTEGER,
                event_type TEXT,
                detail     TEXT,
                created_at TEXT
            );

            -- 会话上下文摘要（增量持久化）
            CREATE TABLE IF NOT EXISTS session_summaries (
                id                     TEXT PRIMARY KEY,
                session_id             TEXT NOT NULL UNIQUE,
                summary_content        TEXT NOT NULL DEFAULT '',
                summarized_through_id  TEXT,
                summary_token_count    INTEGER DEFAULT 0,
                created_at             TEXT,
                updated_at             TEXT
            );
        """)
        await db.commit()

        # 迁移：旧 agents 表可能缺少 model_id / compress_config 列
        cursor = await db.execute("PRAGMA table_info(agents)")
        columns = {row[1] for row in await cursor.fetchall()}
        changed = False
        if "model_id" not in columns:
            await db.execute("ALTER TABLE agents ADD COLUMN model_id TEXT")
            changed = True
            if "model_name" in columns:
                await db.execute("UPDATE agents SET model_id = model_name WHERE model_id IS NULL")
        if "compress_config" not in columns:
            await db.execute("ALTER TABLE agents ADD COLUMN compress_config TEXT")
            changed = True
        if "engine_config" not in columns:
            await db.execute("ALTER TABLE agents ADD COLUMN engine_config TEXT")
            changed = True
        if "tools" not in columns:
            await db.execute("ALTER TABLE agents ADD COLUMN tools TEXT DEFAULT '[]'")
            changed = True
        if changed:
            await db.commit()

        # 迁移：sessions 可能缺少 current_task_id 列（后台任务追踪）
        cursor = await db.execute("PRAGMA table_info(sessions)")
        columns = {row[1] for row in await cursor.fetchall()}
        changed = False
        if "current_task_id" not in columns:
            await db.execute("ALTER TABLE sessions ADD COLUMN current_task_id TEXT")
            changed = True
        if "input_tokens" not in columns:
            await db.execute("ALTER TABLE sessions ADD COLUMN input_tokens INTEGER DEFAULT 0")
            changed = True
        if "output_tokens" not in columns:
            await db.execute("ALTER TABLE sessions ADD COLUMN output_tokens INTEGER DEFAULT 0")
            changed = True
        if "cost_usd" not in columns:
            await db.execute("ALTER TABLE sessions ADD COLUMN cost_usd REAL DEFAULT 0")
            changed = True
        if changed:
            await db.commit()

        # 恢复：服务器重启时，将遗留的 running 会话重置为 active
        await db.execute(
            "UPDATE sessions SET status = 'active', current_task_id = NULL WHERE status = 'running'"
        )
        await db.commit()

        # 迁移：trace_log 可能缺少 agent_name / detail_size 列
        cursor = await db.execute("PRAGMA table_info(trace_log)")
        columns = {row[1] for row in await cursor.fetchall()}
        changed = False
        if "agent_name" not in columns:
            await db.execute("ALTER TABLE trace_log ADD COLUMN agent_name TEXT")
            changed = True
        if "detail_size" not in columns:
            await db.execute("ALTER TABLE trace_log ADD COLUMN detail_size INTEGER DEFAULT 0")
            # 回填已有记录的 detail_size
            await db.execute(
                "UPDATE trace_log SET detail_size = LENGTH(detail) WHERE detail_size IS NULL OR detail_size = 0"
            )
            changed = True
        if changed:
            await db.commit()

        # 迁移：cost_log 可能缺少 agent_name / currency 列
        cursor = await db.execute("PRAGMA table_info(cost_log)")
        columns = {row[1] for row in await cursor.fetchall()}
        changed = False
        if "agent_name" not in columns:
            await db.execute("ALTER TABLE cost_log ADD COLUMN agent_name TEXT")
            changed = True
        if "currency" not in columns:
            await db.execute("ALTER TABLE cost_log ADD COLUMN currency TEXT")
            changed = True
        if changed:
            await db.commit()

        # 迁移：models 可能缺少 input_price / output_price / currency 列
        cursor = await db.execute("PRAGMA table_info(models)")
        columns = {row[1] for row in await cursor.fetchall()}
        changed = False
        if "input_price" not in columns:
            await db.execute("ALTER TABLE models ADD COLUMN input_price REAL")
            changed = True
        if "output_price" not in columns:
            await db.execute("ALTER TABLE models ADD COLUMN output_price REAL")
            changed = True
        if "currency" not in columns:
            await db.execute("ALTER TABLE models ADD COLUMN currency TEXT DEFAULT 'USD'")
            changed = True
        if changed:
            await db.commit()

        # 创建查询优化索引（IF NOT EXISTS 确保幂等）
        await db.executescript("""
            -- cost_log 索引：支持 JOIN 条件、WHERE 过滤、ORDER BY
            CREATE INDEX IF NOT EXISTS idx_cost_session_task
                ON cost_log(session_id, task_id);
            CREATE INDEX IF NOT EXISTS idx_cost_created_at
                ON cost_log(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_cost_session_created
                ON cost_log(session_id, created_at DESC);

            -- trace_log 索引：支持 JOIN 条件、WHERE 过滤、子查询、ORDER BY
            CREATE INDEX IF NOT EXISTS idx_trace_session_task_event
                ON trace_log(session_id, task_id, event_type);
            CREATE INDEX IF NOT EXISTS idx_trace_created_at
                ON trace_log(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_trace_session_created
                ON trace_log(session_id, created_at DESC);
        """)

        # 启动时清理过期数据
        await cleanup_old_records(db=db)


async def cleanup_old_records(
    trace_days: int = 30,
    cost_days: int = 90,
    db: aiosqlite.Connection | None = None,
) -> dict:
    """清理过期的 trace_log 和 cost_log 记录。

    trace_log 保留 trace_days 天（默认 30），cost_log 保留 cost_days 天（默认 90）。
    返回各表删除的行数。可在 init_db 启动时调用，也可通过 API 手动触发。
    """
    trace_cutoff = (datetime.utcnow() - timedelta(days=trace_days)).isoformat()
    cost_cutoff = (datetime.utcnow() - timedelta(days=cost_days)).isoformat()
    result = {"trace_deleted": 0, "cost_deleted": 0}

    async def _do_cleanup(conn: aiosqlite.Connection):
        cursor = await conn.execute(
            "DELETE FROM trace_log WHERE created_at < ?", (trace_cutoff,)
        )
        result["trace_deleted"] = cursor.rowcount
        cursor = await conn.execute(
            "DELETE FROM cost_log WHERE created_at < ?", (cost_cutoff,)
        )
        result["cost_deleted"] = cursor.rowcount
        await conn.commit()

    if db is not None:
        await _do_cleanup(db)
    else:
        async with get_db() as conn:
            await _do_cleanup(conn)

    return result
