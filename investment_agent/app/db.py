import shutil

import aiosqlite
from contextlib import asynccontextmanager
from pathlib import Path

from ..config import get_settings, PROJECT_ROOT



DB_PATH = PROJECT_ROOT / Path(get_settings().get("db", {}).get("sqlite_path", "./data/agent.db")).resolve()



@asynccontextmanager
async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


async def init_db() -> None:
    async with get_db() as db:
        await db.executescript("""
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
                created_at    TEXT,
                updated_at    TEXT
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id         TEXT PRIMARY KEY,
                agent_id   TEXT,
                title      TEXT,
                status     TEXT DEFAULT 'active',
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS messages (
                id          TEXT PRIMARY KEY,
                session_id  TEXT NOT NULL,
                role        TEXT NOT NULL,
                content     TEXT,
                tool_calls  TEXT,
                token_usage TEXT,
                created_at  TEXT
            );

            CREATE TABLE IF NOT EXISTS checkpoints (
                task_id    TEXT PRIMARY KEY,
                session_id TEXT,
                step       INTEGER DEFAULT 0,
                messages   TEXT,
                status     TEXT DEFAULT 'running',
                updated_at TEXT
            );

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

            CREATE TABLE IF NOT EXISTS trace_log (
                id         TEXT PRIMARY KEY,
                session_id TEXT,
                task_id    TEXT,
                step       INTEGER,
                event_type TEXT,
                detail     TEXT,
                created_at TEXT
            );
        """)
        await db.commit()

        # migrate agents table: add model_id/compress_config if missing (old schema used model_name/model_provider)
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
        if changed:
            await db.commit()
