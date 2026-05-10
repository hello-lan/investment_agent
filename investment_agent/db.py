import shutil

import aiosqlite
from contextlib import asynccontextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LEGACY_DB_PATH = Path(__file__).resolve().parent / "investment_agent.db"
DB_PATH = PROJECT_ROOT / "investment_agent.db"


def _migrate_legacy_db_if_needed() -> None:
    if DB_PATH.exists() or not LEGACY_DB_PATH.exists():
        return
    shutil.move(str(LEGACY_DB_PATH), str(DB_PATH))


@asynccontextmanager
async def get_db():
    _migrate_legacy_db_if_needed()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        yield db


async def init_db() -> None:
    _migrate_legacy_db_if_needed()
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

        # migrate agents table: add model_id if missing (old schema used model_name/model_provider)
        cursor = await db.execute("PRAGMA table_info(agents)")
        columns = {row[1] for row in await cursor.fetchall()}
        if "model_id" not in columns:
            await db.execute("ALTER TABLE agents ADD COLUMN model_id TEXT")
            if "model_name" in columns:
                await db.execute("UPDATE agents SET model_id = model_name WHERE model_id IS NULL")
            await db.commit()
