"""Database migration runner — applies numbered SQL files on startup.

Tracks applied migrations in a `_migrations` table. Each .sql file in the
migrations directory is run exactly once, in order. All statements use
IF NOT EXISTS / IF EXISTS so they are safe to re-run.

Migration files are named: 001_description.sql, 002_description.sql, etc.
"""

import logging
import os
from pathlib import Path

import asyncpg

logger = logging.getLogger(__name__)

# Migrations directory relative to repo root.
# In Docker: /app/infra/migrations
# In local dev: resolved relative to this file
_MIGRATIONS_DIR = os.getenv(
    "MIGRATIONS_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "infra", "migrations"),
)


async def run_migrations(pool: asyncpg.Pool) -> int:
    """Apply pending migrations. Returns the number of migrations applied."""
    migrations_dir = Path(_MIGRATIONS_DIR)
    if not migrations_dir.is_dir():
        logger.warning("Migrations directory not found: %s", migrations_dir)
        return 0

    # Ensure the tracking table exists
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            id          SERIAL PRIMARY KEY,
            filename    TEXT NOT NULL UNIQUE,
            applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # Get already-applied migrations
    rows = await pool.fetch("SELECT filename FROM _migrations ORDER BY filename")
    applied = {r["filename"] for r in rows}

    # Discover migration files (sorted by name = sorted by number)
    sql_files = sorted(
        f for f in migrations_dir.iterdir()
        if f.suffix == ".sql" and f.name[0].isdigit()
    )

    applied_count = 0
    for sql_file in sql_files:
        if sql_file.name in applied:
            continue

        sql = sql_file.read_text(encoding="utf-8")
        logger.info("Applying migration: %s", sql_file.name)

        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO _migrations (filename) VALUES ($1)",
                    sql_file.name,
                )

        applied_count += 1
        logger.info("Migration applied: %s", sql_file.name)

    if applied_count == 0:
        logger.info("Database is up to date (no pending migrations)")
    else:
        logger.info("Applied %d migration(s)", applied_count)

    return applied_count
