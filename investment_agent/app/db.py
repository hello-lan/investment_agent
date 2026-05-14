import shutil

import aiosqlite
from contextlib import asynccontextmanager
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
        if changed:
            await db.commit()

        # 迁移：trace_log 可能缺少 agent_name 列
        cursor = await db.execute("PRAGMA table_info(trace_log)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "agent_name" not in columns:
            await db.execute("ALTER TABLE trace_log ADD COLUMN agent_name TEXT")
            await db.commit()
