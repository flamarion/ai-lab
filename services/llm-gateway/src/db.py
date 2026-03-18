"""Database layer — asyncpg connection pool and conversation persistence."""

import logging
import uuid

import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def init_pool(dsn: str) -> None:
    """Create the connection pool. Call once at startup."""
    global _pool
    _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
    logger.info("Database pool created")


async def close_pool() -> None:
    """Drain and close the pool. Call on shutdown."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")


def _pool_or_raise() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialized")
    return _pool


# --- Conversations ---


async def upsert_conversation(conversation_id: str, model: str, title: str) -> None:
    """Insert a conversation or update its updated_at timestamp."""
    pool = _pool_or_raise()
    await pool.execute(
        """
        INSERT INTO conversations (id, model, title, created_at, updated_at)
        VALUES ($1, $2, $3, now(), now())
        ON CONFLICT (id) DO UPDATE SET updated_at = now()
        """,
        uuid.UUID(conversation_id),
        model,
        title[:80],
    )


async def list_conversations(limit: int = 50) -> list[dict]:
    """Return recent conversations ordered by last activity."""
    pool = _pool_or_raise()
    rows = await pool.fetch(
        """
        SELECT id, title, model, created_at, updated_at
        FROM conversations
        ORDER BY updated_at DESC
        LIMIT $1
        """,
        limit,
    )
    return [
        {
            "id": str(r["id"]),
            "title": r["title"],
            "model": r["model"],
            "created_at": r["created_at"].isoformat(),
            "updated_at": r["updated_at"].isoformat(),
        }
        for r in rows
    ]


async def get_conversation(conversation_id: str) -> dict | None:
    """Return conversation metadata or None if not found."""
    pool = _pool_or_raise()
    row = await pool.fetchrow(
        "SELECT id, title, model, created_at, updated_at FROM conversations WHERE id = $1",
        uuid.UUID(conversation_id),
    )
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "model": row["model"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
    }


async def get_messages(conversation_id: str) -> list[dict]:
    """Return all messages for a conversation in chronological order."""
    pool = _pool_or_raise()
    rows = await pool.fetch(
        """
        SELECT role, content, created_at
        FROM messages
        WHERE conversation_id = $1
        ORDER BY created_at ASC
        """,
        uuid.UUID(conversation_id),
    )
    return [
        {"role": r["role"], "content": r["content"], "created_at": r["created_at"].isoformat()}
        for r in rows
    ]


async def add_message(conversation_id: str, role: str, content: str) -> None:
    """Append a message to a conversation."""
    pool = _pool_or_raise()
    await pool.execute(
        """
        INSERT INTO messages (conversation_id, role, content)
        VALUES ($1, $2, $3)
        """,
        uuid.UUID(conversation_id),
        role,
        content,
    )


async def delete_conversation(conversation_id: str) -> bool:
    """Delete a conversation and its messages. Returns True if it existed."""
    pool = _pool_or_raise()
    result = await pool.execute(
        "DELETE FROM conversations WHERE id = $1",
        uuid.UUID(conversation_id),
    )
    return result == "DELETE 1"


def is_available() -> bool:
    """Check if the database pool is initialized."""
    return _pool is not None
