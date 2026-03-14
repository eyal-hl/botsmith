"""SQLite-backed TTL cache for API responses."""

from __future__ import annotations

import json
import logging
import time

import aiosqlite

from bot import config

logger = logging.getLogger(__name__)

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(str(config.CACHE_DB))
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                expires_at REAL NOT NULL
            )
            """
        )
        await _db.execute(
            """
            CREATE TABLE IF NOT EXISTS execution_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                skill_id TEXT NOT NULL,
                executed_at REAL NOT NULL,
                success INTEGER NOT NULL,
                error_message TEXT,
                duration_ms REAL
            )
            """
        )
        await _db.commit()
    return _db


async def get(key: str) -> dict | list | str | None:
    db = await get_db()
    cursor = await db.execute(
        "SELECT value FROM cache WHERE key = ? AND expires_at > ?",
        (key, time.time()),
    )
    row = await cursor.fetchone()
    if row:
        return json.loads(row[0])
    return None


async def set(key: str, value: dict | list | str, ttl: int) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
        (key, json.dumps(value), time.time() + ttl),
    )
    await db.commit()


async def log_execution(
    skill_id: str, success: bool, error_message: str | None, duration_ms: float
) -> None:
    db = await get_db()
    await db.execute(
        "INSERT INTO execution_log (skill_id, executed_at, success, error_message, duration_ms) VALUES (?, ?, ?, ?, ?)",
        (skill_id, time.time(), int(success), error_message, duration_ms),
    )
    await db.commit()


async def get_consecutive_failures(skill_id: str) -> int:
    db = await get_db()
    cursor = await db.execute(
        """
        SELECT success FROM execution_log
        WHERE skill_id = ?
        ORDER BY executed_at DESC
        LIMIT 10
        """,
        (skill_id,),
    )
    count = 0
    async for row in cursor:
        if row[0] == 0:
            count += 1
        else:
            break
    return count


async def cleanup() -> None:
    db = await get_db()
    await db.execute("DELETE FROM cache WHERE expires_at < ?", (time.time(),))
    # Keep only last 1000 execution log entries
    await db.execute(
        """
        DELETE FROM execution_log WHERE id NOT IN (
            SELECT id FROM execution_log ORDER BY executed_at DESC LIMIT 1000
        )
        """
    )
    await db.commit()


async def close() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None
