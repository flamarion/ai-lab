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


def get_pool() -> asyncpg.Pool | None:
    """Return the connection pool (or None if not initialized)."""
    return _pool


def _pool_or_raise() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool not initialized")
    return _pool


# --- Conversations ---


async def upsert_conversation(
    conversation_id: str, model: str, title: str, user_id: str | None = None
) -> None:
    """Insert a conversation or update its updated_at timestamp."""
    pool = _pool_or_raise()
    await pool.execute(
        """
        INSERT INTO conversations (id, model, title, user_id, created_at, updated_at)
        VALUES ($1, $2, $3, $4, now(), now())
        ON CONFLICT (id) DO UPDATE SET updated_at = now()
        """,
        uuid.UUID(conversation_id),
        model,
        title[:80],
        uuid.UUID(user_id) if user_id else None,
    )


async def list_conversations(limit: int = 50, user_id: str | None = None) -> list[dict]:
    """Return recent conversations ordered by last activity, optionally filtered by user."""
    pool = _pool_or_raise()
    if user_id:
        rows = await pool.fetch(
            """
            SELECT id, title, model, created_at, updated_at
            FROM conversations
            WHERE user_id = $1
            ORDER BY updated_at DESC
            LIMIT $2
            """,
            uuid.UUID(user_id),
            limit,
        )
    else:
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


async def update_conversation_title(conversation_id: str, title: str) -> None:
    """Update the title of an existing conversation."""
    pool = _pool_or_raise()
    await pool.execute(
        "UPDATE conversations SET title = $1 WHERE id = $2",
        title[:80],
        uuid.UUID(conversation_id),
    )


async def delete_conversation(conversation_id: str) -> bool:
    """Delete a conversation and its messages. Returns True if it existed."""
    pool = _pool_or_raise()
    result = await pool.execute(
        "DELETE FROM conversations WHERE id = $1",
        uuid.UUID(conversation_id),
    )
    return result == "DELETE 1"


# --- Documents (RAG) ---


async def add_document(source: str, num_chunks: int) -> str:
    """Insert a document record and return its ID."""
    pool = _pool_or_raise()
    row = await pool.fetchrow(
        """
        INSERT INTO documents (source, num_chunks)
        VALUES ($1, $2)
        RETURNING id
        """,
        source,
        num_chunks,
    )
    return str(row["id"])


async def list_documents(limit: int = 50) -> list[dict]:
    """Return ingested documents ordered by creation date."""
    pool = _pool_or_raise()
    rows = await pool.fetch(
        """
        SELECT id, source, num_chunks, created_at
        FROM documents
        ORDER BY created_at DESC
        LIMIT $1
        """,
        limit,
    )
    return [
        {
            "id": str(r["id"]),
            "source": r["source"],
            "num_chunks": r["num_chunks"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


async def delete_document(document_id: str) -> bool:
    """Delete a document record. Returns True if it existed."""
    pool = _pool_or_raise()
    result = await pool.execute(
        "DELETE FROM documents WHERE id = $1",
        uuid.UUID(document_id),
    )
    return result == "DELETE 1"


# --- Users ---


async def create_user(username: str, pin_hash: str) -> str:
    """Create a user and return their ID."""
    pool = _pool_or_raise()
    row = await pool.fetchrow(
        "INSERT INTO users (username, pin_hash) VALUES ($1, $2) RETURNING id",
        username,
        pin_hash,
    )
    return str(row["id"])


async def get_user_by_username(username: str) -> dict | None:
    """Return user by username or None."""
    pool = _pool_or_raise()
    row = await pool.fetchrow(
        "SELECT id, username, pin_hash, preferences, created_at FROM users WHERE username = $1",
        username,
    )
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "username": row["username"],
        "pin_hash": row["pin_hash"],
        "preferences": row["preferences"],
    }


async def list_users() -> list[dict]:
    """Return all users (id + username only, no secrets)."""
    pool = _pool_or_raise()
    rows = await pool.fetch("SELECT id, username FROM users ORDER BY username")
    return [{"id": str(r["id"]), "username": r["username"]} for r in rows]


async def update_user_preferences(user_id: str, preferences: dict) -> None:
    """Update a user's preferences JSON."""
    pool = _pool_or_raise()
    import json
    await pool.execute(
        "UPDATE users SET preferences = $1 WHERE id = $2",
        json.dumps(preferences),
        uuid.UUID(user_id),
    )


def is_available() -> bool:
    """Check if the database pool is initialized."""
    return _pool is not None
