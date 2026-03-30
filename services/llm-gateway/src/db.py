"""Database layer — asyncpg connection pool and conversation persistence."""

import json
import logging
import uuid

import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Configure each connection in the pool.

    asyncpg returns json/jsonb columns as raw strings by default.
    Register codecs so they round-trip as Python dicts/lists automatically.
    """
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )
    await conn.set_type_codec(
        "json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def init_pool(dsn: str) -> None:
    """Create the connection pool. Call once at startup."""
    global _pool
    _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10, init=_init_connection)
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
        ON CONFLICT (id) DO UPDATE SET
            updated_at = now(),
            user_id = COALESCE(conversations.user_id, EXCLUDED.user_id)
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


async def create_user(username: str, pin_hash: str, is_admin: bool = False) -> str:
    """Create a user and return their ID."""
    pool = _pool_or_raise()
    row = await pool.fetchrow(
        "INSERT INTO users (username, pin_hash, is_admin) VALUES ($1, $2, $3) RETURNING id",
        username,
        pin_hash,
        is_admin,
    )
    return str(row["id"])


async def get_user_by_username(username: str) -> dict | None:
    """Return user by username or None."""
    pool = _pool_or_raise()
    row = await pool.fetchrow(
        "SELECT id, username, pin_hash, is_admin, is_child, preferences, created_at FROM users WHERE username = $1",
        username,
    )
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "username": row["username"],
        "pin_hash": row["pin_hash"],
        "is_admin": row["is_admin"],
        "is_child": row["is_child"],
        "preferences": row["preferences"],
    }


async def get_user_by_id(user_id: str) -> dict | None:
    """Return user by ID or None (includes pin_hash for verification)."""
    pool = _pool_or_raise()
    row = await pool.fetchrow(
        "SELECT id, username, pin_hash, is_admin, is_child, preferences FROM users WHERE id = $1",
        uuid.UUID(user_id),
    )
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "username": row["username"],
        "pin_hash": row["pin_hash"],
        "is_admin": row["is_admin"],
        "is_child": row["is_child"],
        "preferences": row["preferences"],
    }


async def list_users() -> list[dict]:
    """Return all users (id, username, is_admin, is_child — no secrets)."""
    pool = _pool_or_raise()
    rows = await pool.fetch("SELECT id, username, is_admin, is_child FROM users ORDER BY username")
    return [
        {
            "id": str(r["id"]),
            "username": r["username"],
            "is_admin": r["is_admin"],
            "is_child": r["is_child"],
        }
        for r in rows
    ]


async def update_user_preferences(user_id: str, preferences: dict) -> bool:
    """Update a user's preferences JSON. Returns True if user exists."""
    pool = _pool_or_raise()
    result = await pool.execute(
        "UPDATE users SET preferences = $1 WHERE id = $2",
        preferences,
        uuid.UUID(user_id),
    )
    return result == "UPDATE 1"


async def update_user_pin(user_id: str, pin_hash: str) -> bool:
    """Update a user's PIN hash. Returns True if user exists."""
    pool = _pool_or_raise()
    result = await pool.execute(
        "UPDATE users SET pin_hash = $1 WHERE id = $2",
        pin_hash,
        uuid.UUID(user_id),
    )
    return result == "UPDATE 1"


async def update_user_admin(user_id: str, is_admin: bool) -> bool:
    """Toggle admin status. Returns True if user exists."""
    pool = _pool_or_raise()
    result = await pool.execute(
        "UPDATE users SET is_admin = $1 WHERE id = $2",
        is_admin,
        uuid.UUID(user_id),
    )
    return result == "UPDATE 1"


async def update_user_child(user_id: str, is_child: bool) -> bool:
    """Toggle child flag. Returns True if user exists."""
    pool = _pool_or_raise()
    result = await pool.execute(
        "UPDATE users SET is_child = $1 WHERE id = $2",
        is_child,
        uuid.UUID(user_id),
    )
    return result == "UPDATE 1"


async def delete_user(user_id: str) -> bool:
    """Delete a user. Returns True if existed."""
    pool = _pool_or_raise()
    result = await pool.execute(
        "DELETE FROM users WHERE id = $1",
        uuid.UUID(user_id),
    )
    return result == "DELETE 1"


async def count_users() -> int:
    """Return the total number of users."""
    pool = _pool_or_raise()
    return await pool.fetchval("SELECT COUNT(*) FROM users")


def is_available() -> bool:
    """Check if the database pool is initialized."""
    return _pool is not None


# --- Secrets ---


async def list_secrets() -> list[dict]:
    """Return all secret keys (values masked)."""
    pool = _pool_or_raise()
    rows = await pool.fetch("SELECT key, created_at FROM secrets ORDER BY key")
    return [{"key": r["key"], "created_at": r["created_at"].isoformat()} for r in rows]


async def get_secret(key: str) -> str | None:
    """Return a secret value by key, or None."""
    pool = _pool_or_raise()
    return await pool.fetchval("SELECT value FROM secrets WHERE key = $1", key)


async def get_all_secrets() -> dict[str, str]:
    """Return all secrets as a {key: value} dict (for substitution)."""
    pool = _pool_or_raise()
    rows = await pool.fetch("SELECT key, value FROM secrets")
    return {r["key"]: r["value"] for r in rows}


async def set_secret(key: str, value: str) -> None:
    """Create or update a secret."""
    pool = _pool_or_raise()
    await pool.execute(
        "INSERT INTO secrets (key, value) VALUES ($1, $2) "
        "ON CONFLICT (key) DO UPDATE SET value = $2",
        key, value,
    )


async def delete_secret(key: str) -> bool:
    """Delete a secret. Returns True if it existed."""
    pool = _pool_or_raise()
    result = await pool.execute("DELETE FROM secrets WHERE key = $1", key)
    return result == "DELETE 1"


# --- MCP Config ---


async def get_mcp_config() -> dict:
    """Return the persisted MCP server config from the DB."""
    pool = _pool_or_raise()
    row = await pool.fetchrow("SELECT config FROM mcp_config WHERE id = 1")
    if row and row["config"]:
        return row["config"]
    return {}


async def save_mcp_config(config: dict) -> None:
    """Persist the full MCP server config to the DB."""
    pool = _pool_or_raise()
    await pool.execute(
        "INSERT INTO mcp_config (id, config, updated_at) VALUES (1, $1, now()) "
        "ON CONFLICT (id) DO UPDATE SET config = $1, updated_at = now()",
        config,
    )


# --- Agents ---


async def list_agents() -> list[dict]:
    """Return all agents ordered by name."""
    pool = _pool_or_raise()
    rows = await pool.fetch(
        "SELECT id, name, description, system_prompt, model, tools, "
        "routing_keywords, enabled, created_at, updated_at "
        "FROM agents ORDER BY name"
    )
    return [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "description": r["description"],
            "system_prompt": r["system_prompt"],
            "model": r["model"],
            "tools": list(r["tools"]),
            "routing_keywords": list(r["routing_keywords"]),
            "enabled": r["enabled"],
            "created_at": r["created_at"].isoformat(),
            "updated_at": r["updated_at"].isoformat(),
        }
        for r in rows
    ]


async def upsert_agent(config: dict) -> str:
    """Create or update an agent by name. Returns the agent ID."""
    pool = _pool_or_raise()
    row = await pool.fetchrow(
        """
        INSERT INTO agents (name, description, system_prompt, model, tools, routing_keywords, enabled)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (name) DO UPDATE SET
            description = EXCLUDED.description,
            system_prompt = EXCLUDED.system_prompt,
            model = EXCLUDED.model,
            tools = EXCLUDED.tools,
            routing_keywords = EXCLUDED.routing_keywords,
            enabled = EXCLUDED.enabled,
            updated_at = now()
        RETURNING id
        """,
        config["name"],
        config.get("description", ""),
        config.get("system_prompt", ""),
        config.get("model"),
        config.get("tools", []),
        config.get("routing_keywords", []),
        config.get("enabled", True),
    )
    return str(row["id"])


async def delete_agent(agent_id: str) -> bool:
    """Delete an agent by ID. Returns True if it existed."""
    pool = _pool_or_raise()
    result = await pool.execute(
        "DELETE FROM agents WHERE id = $1",
        uuid.UUID(agent_id),
    )
    return result == "DELETE 1"


# --- User Memory ---


async def list_user_memories(user_id: str) -> list[dict]:
    """Return all memory entries for a user."""
    pool = _pool_or_raise()
    rows = await pool.fetch(
        "SELECT id, content, created_at, updated_at FROM user_memory "
        "WHERE user_id = $1 ORDER BY created_at",
        uuid.UUID(user_id),
    )
    return [
        {
            "id": str(r["id"]),
            "content": r["content"],
            "created_at": r["created_at"].isoformat(),
            "updated_at": r["updated_at"].isoformat(),
        }
        for r in rows
    ]


async def get_user_memory_text(user_id: str) -> str:
    """Return all memories for a user as a single text block for system prompt injection."""
    pool = _pool_or_raise()
    rows = await pool.fetch(
        "SELECT content FROM user_memory WHERE user_id = $1 ORDER BY created_at",
        uuid.UUID(user_id),
    )
    return "\n".join(r["content"] for r in rows)


async def add_user_memory(user_id: str, content: str) -> str:
    """Add a memory entry. Returns the new memory ID."""
    pool = _pool_or_raise()
    row = await pool.fetchrow(
        "INSERT INTO user_memory (user_id, content) VALUES ($1, $2) RETURNING id",
        uuid.UUID(user_id), content,
    )
    return str(row["id"])


async def update_user_memory(memory_id: str, content: str) -> bool:
    """Update a memory entry. Returns True if it existed."""
    pool = _pool_or_raise()
    result = await pool.execute(
        "UPDATE user_memory SET content = $1, updated_at = now() WHERE id = $2",
        content, uuid.UUID(memory_id),
    )
    return result == "UPDATE 1"


async def delete_user_memory(memory_id: str, user_id: str | None = None) -> bool:
    """Delete a memory entry. If user_id is provided, enforces ownership."""
    pool = _pool_or_raise()
    if user_id:
        result = await pool.execute(
            "DELETE FROM user_memory WHERE id = $1 AND user_id = $2",
            uuid.UUID(memory_id), uuid.UUID(user_id),
        )
    else:
        result = await pool.execute(
            "DELETE FROM user_memory WHERE id = $1",
            uuid.UUID(memory_id),
        )
    return result == "DELETE 1"
