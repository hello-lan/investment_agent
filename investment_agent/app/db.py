import shutil

import aiosqlite
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
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


async def _ensure_columns(
    db: aiosqlite.Connection,
    migrations: list[tuple[str, str, str]],
) -> None:
    """批量检查并添加缺失列。

    Args:
        db: 数据库连接
        migrations: (表名, 列名, 类型定义) 列表
    """
    # 按表分组，减少 PRAGMA 调用
    by_table: dict[str, list[tuple[str, str]]] = {}
    for table, col, col_type in migrations:
        by_table.setdefault(table, []).append((col, col_type))

    for table, columns in by_table.items():
        cursor = await db.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in await cursor.fetchall()}
        changed = False
        for col, col_type in columns:
            if col not in existing:
                await db.execute(
                    f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"
                )
                changed = True
        if changed:
            await db.commit()


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
                agent_name    TEXT,
                input_tokens  INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cache_read_tokens     INTEGER DEFAULT 0,
                cache_creation_tokens INTEGER DEFAULT 0,
                cache_hit_ratio       REAL DEFAULT 0,
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

        # ── 声明式列迁移 ──────────────────────────────────────────────
        # 格式: (表名, 列名, 类型定义)
        # 按表分组执行，减少 PRAGMA 调用次数
        column_migrations: list[tuple[str, str, str]] = [
            ("agents", "model_id", "TEXT"),
            ("agents", "compress_config", "TEXT"),
            ("agents", "engine_config", "TEXT"),
            ("agents", "tools", "TEXT DEFAULT '[]'"),
            ("sessions", "current_task_id", "TEXT"),
            ("sessions", "input_tokens", "INTEGER DEFAULT 0"),
            ("sessions", "output_tokens", "INTEGER DEFAULT 0"),
            ("sessions", "cost_usd", "REAL DEFAULT 0"),
            ("trace_log", "agent_name", "TEXT"),
            ("trace_log", "detail_size", "INTEGER DEFAULT 0"),
            ("cost_log", "agent_name", "TEXT"),
            ("cost_log", "currency", "TEXT"),
            ("cost_log", "cache_read_tokens", "INTEGER DEFAULT 0"),
            ("cost_log", "cache_creation_tokens", "INTEGER DEFAULT 0"),
            ("cost_log", "cache_hit_ratio", "REAL DEFAULT 0"),
            ("models", "input_price", "REAL"),
            ("models", "output_price", "REAL"),
            ("models", "currency", "TEXT DEFAULT 'USD'"),
        ]
        await _ensure_columns(db, column_migrations)

        # ── 特殊迁移（数据回填）──────────────────────────────────────
        # agents.model_id: 从旧列 model_name 回填
        cursor = await db.execute("PRAGMA table_info(agents)")
        agent_cols = {row[1] for row in await cursor.fetchall()}
        if "model_name" in agent_cols:
            await db.execute(
                "UPDATE agents SET model_id = model_name WHERE model_id IS NULL"
            )
            await db.commit()


    # 添加 models 表的 provider_type 字段（优化1：多provider缓存支持）
    try:
        await db.execute("ALTER TABLE models ADD COLUMN provider_type TEXT DEFAULT 'openai_compat'")
    except Exception:
        pass

    # 添加 models 表的 enable_cache 字段
    try:
        await db.execute("ALTER TABLE models ADD COLUMN enable_cache BOOLEAN DEFAULT 1")
    except Exception:
        pass

    # 添加 cost_log 表的缓存指标字段
    try:
        await db.execute("ALTER TABLE cost_log ADD COLUMN cache_creation_tokens INTEGER DEFAULT 0")
    except Exception:
        pass

    try:
        await db.execute("ALTER TABLE cost_log ADD COLUMN cache_read_tokens INTEGER DEFAULT 0")
    except Exception:
        pass
        # trace_log.detail_size: 回填已有记录
        await db.execute(
            "UPDATE trace_log SET detail_size = LENGTH(detail) "
            "WHERE detail_size IS NULL OR detail_size = 0"
        )
        await db.commit()

        # ── 恢复：服务器重启时，将遗留的 running 会话重置为 active ──
        await db.execute(
            "UPDATE sessions SET status = 'active', current_task_id = NULL WHERE status = 'running'"
        )

    # 添加 models 表的 provider_type 字段（优化1：多provider缓存支持）
    try:
        await db.execute("ALTER TABLE models ADD COLUMN provider_type TEXT DEFAULT 'openai_compat'")
    except Exception:
        pass

    # 添加 models 表的 enable_cache 字段
    try:
        await db.execute("ALTER TABLE models ADD COLUMN enable_cache BOOLEAN DEFAULT 1")
    except Exception:
        pass

    # 添加 cost_log 表的缓存指标字段
    try:
        await db.execute("ALTER TABLE cost_log ADD COLUMN cache_creation_tokens INTEGER DEFAULT 0")
    except Exception:
        pass

    try:
        await db.execute("ALTER TABLE cost_log ADD COLUMN cache_read_tokens INTEGER DEFAULT 0")
    except Exception:
        pass

        await db.commit()

        # ── 创建查询优化索引（IF NOT EXISTS 确保幂等）──────────────
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
    trace_cutoff = (datetime.now(timezone.utc) - timedelta(days=trace_days)).isoformat()
    cost_cutoff = (datetime.now(timezone.utc) - timedelta(days=cost_days)).isoformat()
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
