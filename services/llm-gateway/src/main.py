import asyncio
import logging
import os
import re
import sys
import uuid
from contextlib import asynccontextmanager

import bcrypt
from fastapi import FastAPI, Form, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

# Add shared module to path (for local dev outside Docker)
_shared_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared", "python")
if os.path.isdir(_shared_path) and _shared_path not in sys.path:
    sys.path.insert(0, _shared_path)

from ai_lab_common.config import settings
from src import chunker, context, db, migrations, router, tools, vector_store
from src.mcp_client import mcp_manager
from src.ollama_client import OllamaClient

logger = logging.getLogger(__name__)

client: OllamaClient | None = None

# RAG prompt template injected as a system message when use_rag=True
_RAG_SYSTEM_PROMPT = (
    "Use the following context to answer the user's question. "
    "If the context doesn't contain relevant information, say so — "
    "do not make up an answer.\n\n"
    "Context:\n{context}"
)

_PIN_PATTERN = re.compile(r"^\d{4,8}$")


def _validate_uuid(value: str) -> uuid.UUID:
    """Parse a UUID string or raise 400."""
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {value}")



@asynccontextmanager
async def lifespan(app: FastAPI):
    global client

    # Create the Ollama client immediately — it's just an httpx client,
    # no connection needed until the first request.
    client = OllamaClient(settings.OLLAMA_HOST)

    # --- Background initialization ---
    # All external connections (DB, Qdrant, Weave, MCP) happen in a
    # background task so the gateway starts serving requests immediately.
    # Services become available as they connect. This prevents slow/hanging
    # external services from blocking login, health checks, etc.
    async def _init_services():
        # Yield to let uvicorn fully start accepting connections.
        # Without this, CPU-intensive MCP initialization (spawning
        # subprocesses, parsing large JSON tool schemas) starves the
        # single-threaded asyncio event loop and blocks TCP accepts.
        await asyncio.sleep(2)

        # Weave
        if settings.WEAVE_ENABLED:
            try:
                import weave

                _original_checkLevel = logging._checkLevel

                def _patched_checkLevel(level):
                    if callable(level) and hasattr(level, "__name__"):
                        level = level.__name__.upper()
                    return _original_checkLevel(level)

                logging._checkLevel = _patched_checkLevel
                try:
                    weave.init(settings.WANDB_PROJECT)
                finally:
                    logging._checkLevel = _original_checkLevel
                logger.info("Weave initialized — project: %s", settings.WANDB_PROJECT)
            except Exception as e:
                logger.warning("Failed to initialize Weave: %s — tracing disabled.", e)
        else:
            logger.info("Weave disabled (WEAVE_ENABLED=%s)", os.getenv("WEAVE_ENABLED", "true"))

        # Database
        try:
            await db.init_pool(settings.DATABASE_URL)
            logger.info("Database connected")
        except Exception as e:
            logger.warning("Failed to connect to database: %s — persistence disabled.", e)

        # Migrations
        if db.is_available():
            try:
                await migrations.run_migrations(db.get_pool())
            except Exception as e:
                logger.warning("Migration failed: %s — schema may be incomplete.", e)

        await asyncio.sleep(0)  # yield to event loop

        # Qdrant
        try:
            vector_store.init_store()
            logger.info("Qdrant connected")
        except Exception as e:
            logger.warning("Failed to connect to Qdrant: %s — RAG disabled.", e)

        await asyncio.sleep(0)  # yield to event loop

        # MCP servers (can be very slow — downloads packages, spawns subprocesses)
        try:
            await mcp_manager.start()
        except Exception as e:
            logger.warning("MCP initialization failed: %s — MCP tools unavailable.", e)

        logger.info("All services initialized")

    init_task = asyncio.create_task(_init_services())

    yield

    init_task.cancel()
    await mcp_manager.stop()
    await client.close()
    await db.close_pool()
    vector_store.close_store()


app = FastAPI(title="AI Lab - LLM Gateway", lifespan=lifespan)


# --- Request/Response Models ---


class ChatRequest(BaseModel):
    message: str
    model: str | None = None
    temperature: float = 0.7
    top_p: float | None = None
    top_k: int | None = None
    num_predict: int | None = None
    repeat_penalty: float | None = None
    seed: int | None = None
    num_ctx: int | None = None
    system_prompt: str | None = None
    use_rag: bool = False
    use_tools: bool = False
    history: list[dict] = []
    conversation_id: str | None = None
    user_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    model: str
    conversation_id: str
    tools_used: list[dict] = []


class RegisterRequest(BaseModel):
    username: str
    pin: str


class LoginRequest(BaseModel):
    username: str
    pin: str


class PreferencesRequest(BaseModel):
    user_id: str
    preferences: dict


class ChangePinRequest(BaseModel):
    user_id: str
    current_pin: str
    new_pin: str


class AdminResetPinRequest(BaseModel):
    admin_user_id: str
    target_user_id: str
    new_pin: str


class AdminToggleRequest(BaseModel):
    admin_user_id: str
    target_user_id: str
    is_admin: bool


class AdminDeleteUserRequest(BaseModel):
    admin_user_id: str
    target_user_id: str


class AdminToggleChildRequest(BaseModel):
    admin_user_id: str
    target_user_id: str
    is_child: bool


class AdminCreateUserRequest(BaseModel):
    admin_user_id: str
    username: str
    pin: str
    is_child: bool = False


# --- Auth Endpoints ---


@app.get("/auth/users")
async def list_users():
    """Return usernames for the login dropdown. Admin details available via /admin endpoints."""
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    users = await db.list_users()
    # Only expose usernames for the login screen — not IDs or admin status
    return {"users": [{"username": u["username"]} for u in users]}


@app.post("/auth/register")
async def register(request: RegisterRequest):
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    if not _PIN_PATTERN.match(request.pin):
        raise HTTPException(status_code=400, detail="PIN must be 4-8 digits")
    if not request.username.strip():
        raise HTTPException(status_code=400, detail="Username is required")

    existing = await db.get_user_by_username(request.username.strip())
    if existing:
        raise HTTPException(status_code=409, detail="Username already taken")

    pin_hash = await run_in_threadpool(
        bcrypt.hashpw, request.pin.encode(), bcrypt.gensalt()
    )

    # First user is auto-admin
    user_count = await db.count_users()
    is_admin = user_count == 0

    user_id = await db.create_user(request.username.strip(), pin_hash.decode(), is_admin)
    return {"user_id": user_id, "username": request.username.strip(), "is_admin": is_admin}


@app.post("/auth/login")
async def login(request: LoginRequest):
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")

    user = await db.get_user_by_username(request.username.strip())
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or PIN")

    valid = await run_in_threadpool(
        bcrypt.checkpw, request.pin.encode(), user["pin_hash"].encode()
    )
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid username or PIN")

    return {
        "user_id": user["id"],
        "username": user["username"],
        "is_admin": user["is_admin"],
        "is_child": user.get("is_child", False),
        "preferences": user["preferences"],
    }


@app.get("/auth/session")
async def get_session(user_id: str = Query(...)):
    """Restore a session from a user_id (e.g. after browser reload).

    Returns the same data as /auth/login but without requiring PIN.
    Security note: relies on UUID unpredictability (v4, 122 bits of entropy)
    rather than a signed token. Acceptable for a LAN-only PIN-auth app;
    would need a proper session token for public-facing deployments.
    """
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    _validate_uuid(user_id)
    user = await db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    from starlette.responses import JSONResponse
    return JSONResponse(
        content={
            "user_id": user["id"],
            "username": user["username"],
            "is_admin": user["is_admin"],
            "is_child": user.get("is_child", False),
            "preferences": user["preferences"],
        },
        headers={"Cache-Control": "no-store"},
    )


@app.patch("/auth/preferences")
async def update_preferences(request: PreferencesRequest):
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    _validate_uuid(request.user_id)
    updated = await db.update_user_preferences(request.user_id, request.preferences)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "updated"}


@app.post("/auth/change-pin")
async def change_pin(request: ChangePinRequest):
    """Allow a user to change their own PIN."""
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    if not _PIN_PATTERN.match(request.new_pin):
        raise HTTPException(status_code=400, detail="New PIN must be 4-8 digits")

    _validate_uuid(request.user_id)
    user = await db.get_user_by_id(request.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    valid = await run_in_threadpool(
        bcrypt.checkpw, request.current_pin.encode(), user["pin_hash"].encode()
    )
    if not valid:
        raise HTTPException(status_code=401, detail="Current PIN is incorrect")

    new_hash = await run_in_threadpool(
        bcrypt.hashpw, request.new_pin.encode(), bcrypt.gensalt()
    )
    await db.update_user_pin(request.user_id, new_hash.decode())
    return {"status": "pin_changed"}


# --- Admin Endpoints ---


async def _require_admin(admin_user_id: str) -> dict:
    """Validate that the given user_id belongs to an admin."""
    _validate_uuid(admin_user_id)
    user = await db.get_user_by_id(admin_user_id)
    if not user or not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


@app.get("/admin/users")
async def admin_list_users(admin_user_id: str = Query(...)):
    """Admin-only: list all users with IDs and admin status."""
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    await _require_admin(admin_user_id)
    users = await db.list_users()
    return {"users": users}


@app.post("/admin/reset-pin")
async def admin_reset_pin(request: AdminResetPinRequest):
    """Admin resets another user's PIN."""
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    await _require_admin(request.admin_user_id)
    if not _PIN_PATTERN.match(request.new_pin):
        raise HTTPException(status_code=400, detail="New PIN must be 4-8 digits")

    _validate_uuid(request.target_user_id)
    new_hash = await run_in_threadpool(
        bcrypt.hashpw, request.new_pin.encode(), bcrypt.gensalt()
    )
    updated = await db.update_user_pin(request.target_user_id, new_hash.decode())
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "pin_reset"}


@app.post("/admin/toggle-admin")
async def admin_toggle_admin(request: AdminToggleRequest):
    """Admin toggles another user's admin status."""
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    await _require_admin(request.admin_user_id)
    _validate_uuid(request.target_user_id)

    if request.admin_user_id == request.target_user_id:
        raise HTTPException(status_code=400, detail="Cannot change your own admin status")

    updated = await db.update_user_admin(request.target_user_id, request.is_admin)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "updated", "is_admin": request.is_admin}


@app.post("/admin/delete-user")
async def admin_delete_user(request: AdminDeleteUserRequest):
    """Admin deletes a user."""
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    await _require_admin(request.admin_user_id)
    _validate_uuid(request.target_user_id)

    if request.admin_user_id == request.target_user_id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    deleted = await db.delete_user(request.target_user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "deleted"}


@app.post("/admin/toggle-child")
async def admin_toggle_child(request: AdminToggleChildRequest):
    """Admin flags/unflags a user as a child."""
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    await _require_admin(request.admin_user_id)
    _validate_uuid(request.target_user_id)

    if request.admin_user_id == request.target_user_id:
        raise HTTPException(status_code=400, detail="Cannot change your own child flag")

    updated = await db.update_user_child(request.target_user_id, request.is_child)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return {"status": "updated", "is_child": request.is_child}


@app.post("/admin/create-user")
async def admin_create_user(request: AdminCreateUserRequest):
    """Admin creates a user account (e.g., for a family member)."""
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    await _require_admin(request.admin_user_id)

    if not _PIN_PATTERN.match(request.pin):
        raise HTTPException(status_code=400, detail="PIN must be 4-8 digits")
    if not request.username.strip():
        raise HTTPException(status_code=400, detail="Username is required")

    existing = await db.get_user_by_username(request.username.strip())
    if existing:
        raise HTTPException(status_code=409, detail="Username already taken")

    pin_hash = await run_in_threadpool(
        bcrypt.hashpw, request.pin.encode(), bcrypt.gensalt()
    )
    user_id = await db.create_user(request.username.strip(), pin_hash.decode())

    if request.is_child:
        await db.update_user_child(user_id, True)

    return {"user_id": user_id, "username": request.username.strip()}


# --- Core Endpoints ---


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "database": db.is_available(),
        "vector_store": vector_store.is_available(),
    }


@app.get("/models")
async def list_models():
    try:
        models = await client.list_models()
        return {"models": [m["name"] for m in models if "embed" not in m["name"].lower()]}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to reach Ollama: {e}")


@app.get("/tools")
async def list_tools():
    """List available tools that can be used with use_tools=True."""
    local_tools = [
        {
            "name": name,
            "description": entry["schema"]["function"]["description"],
            "source": "local",
        }
        for name, entry in tools.TOOL_REGISTRY.items()
    ]
    return {"tools": local_tools + mcp_manager.list_tools()}


# --- MCP Server Management (admin-only — these endpoints can execute commands) ---


class AddMCPServerRequest(BaseModel):
    admin_user_id: str
    name: str
    config: dict  # full server config JSON (same format as Cursor/Claude Desktop)


class MCPAdminRequest(BaseModel):
    admin_user_id: str


@app.get("/mcp/servers")
async def list_mcp_servers(admin_user_id: str = Query(...)):
    """Admin-only: list configured MCP servers with connection status and tools."""
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    await _require_admin(admin_user_id)
    return {"servers": await mcp_manager.list_servers()}


@app.get("/mcp/config")
async def get_full_mcp_config(admin_user_id: str = Query(...)):
    """Admin-only: get the full MCP config in Cursor/Claude Desktop format."""
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    await _require_admin(admin_user_id)
    config = await mcp_manager.get_config()
    return {"mcpServers": config}


class SaveMCPConfigRequest(BaseModel):
    admin_user_id: str
    config: dict  # {"mcpServers": {...}} or just {...}


@app.put("/mcp/config")
async def save_full_mcp_config(request: SaveMCPConfigRequest):
    """Admin-only: replace the entire MCP config and reconnect."""
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    await _require_admin(request.admin_user_id)

    # Accept both {"mcpServers": {...}} and plain {...}
    servers = request.config.get("mcpServers", request.config)
    if not isinstance(servers, dict):
        raise HTTPException(status_code=400, detail="Config must be an object")
    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            raise HTTPException(status_code=400, detail=f"Server '{name}' config must be an object")

    await mcp_manager.save_config(servers)
    await mcp_manager.reload()
    return {
        "status": "saved",
        "servers": await mcp_manager.list_servers(),
    }


@app.get("/mcp/servers/{name}/config")
async def get_mcp_server_config(name: str, admin_user_id: str = Query(...)):
    """Admin-only: get the raw JSON config for an MCP server.

    Returns unredacted config (including env/headers) for editing.
    Use ${SECRET_NAME} placeholders instead of literal secrets to keep
    credentials in the secrets store rather than in the config file.
    """
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    await _require_admin(admin_user_id)
    config = await mcp_manager.get_config()
    if name not in config:
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found")
    return {"name": name, "config": config[name]}


@app.post("/mcp/servers")
async def add_mcp_server(request: AddMCPServerRequest):
    """Admin-only: add MCP server(s) to config and reconnect.

    Accepts either:
    - name + config: single server
    - name + config where config has mcpServers: bulk import (Cursor format)
    """
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    await _require_admin(request.admin_user_id)

    # Detect Cursor-style bulk format: {"mcpServers": {"name1": {...}, ...}}
    if "mcpServers" in request.config:
        servers_dict = request.config["mcpServers"]
        if not isinstance(servers_dict, dict) or not servers_dict:
            raise HTTPException(status_code=400, detail="mcpServers must be a non-empty object")
        added = await mcp_manager.add_servers_bulk(servers_dict)
        await mcp_manager.reload()
        all_servers = await mcp_manager.list_servers()
        return {
            "status": "added",
            "names": added,
            "servers": [s for s in all_servers if s["name"] in added],
        }

    # Single server
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="Server name is required")
    name = request.name.strip()
    await mcp_manager.add_server_config(name, request.config)
    await mcp_manager.reload()
    servers = await mcp_manager.list_servers()
    server_info = next((s for s in servers if s["name"] == name), None)
    connected = server_info["connected"] if server_info else False
    found_tools = server_info["tools"] if server_info else []
    return {
        "status": "added",
        "name": name,
        "connected": connected,
        "tools": found_tools,
    }


@app.delete("/mcp/servers/{name}")
async def remove_mcp_server(name: str, admin_user_id: str = Query(...)):
    """Admin-only: remove an MCP server and reconnect."""
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    await _require_admin(admin_user_id)
    if not await mcp_manager.remove_server(name):
        raise HTTPException(status_code=404, detail=f"Server '{name}' not found")
    await mcp_manager.reload()
    return {"status": "removed", "name": name}


@app.post("/mcp/restart")
async def restart_mcp(request: MCPAdminRequest):
    """Admin-only: reconnect to all configured MCP servers."""
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    await _require_admin(request.admin_user_id)
    await mcp_manager.reload()
    return {"status": "restarted", "tools": mcp_manager.get_tool_names()}



# --- Secrets Management (admin-only) ---


class SecretRequest(BaseModel):
    admin_user_id: str
    key: str
    value: str


@app.get("/secrets")
async def list_secrets_endpoint(admin_user_id: str = Query(...)):
    """Admin-only: list secret keys (values are never exposed)."""
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    await _require_admin(admin_user_id)
    secrets = await db.list_secrets()
    return {"secrets": secrets}


@app.post("/secrets")
async def set_secret_endpoint(request: SecretRequest):
    """Admin-only: create or update a secret."""
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    await _require_admin(request.admin_user_id)
    if not request.key.strip():
        raise HTTPException(status_code=400, detail="Key is required")
    await db.set_secret(request.key.strip(), request.value)
    return {"status": "saved", "key": request.key.strip()}


@app.delete("/secrets/{key}")
async def delete_secret_endpoint(key: str, admin_user_id: str = Query(...)):
    """Admin-only: delete a secret."""
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    await _require_admin(admin_user_id)
    if not await db.delete_secret(key):
        raise HTTPException(status_code=404, detail=f"Secret '{key}' not found")
    return {"status": "deleted", "key": key}


# --- User Memory ---


class MemoryRequest(BaseModel):
    user_id: str
    content: str


@app.get("/memory")
async def list_memories(user_id: str = Query(...)):
    """List all memory entries for a user."""
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    _validate_uuid(user_id)
    memories = await db.list_user_memories(user_id)
    return {"memories": memories}


@app.post("/memory")
async def add_memory(request: MemoryRequest):
    """Add a memory entry for a user (e.g. 'I prefer concise responses')."""
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    _validate_uuid(request.user_id)
    if not request.content.strip():
        raise HTTPException(status_code=400, detail="Content is required")
    memory_id = await db.add_user_memory(request.user_id, request.content.strip())
    return {"status": "saved", "id": memory_id}


@app.delete("/memory/{memory_id}")
async def delete_memory(memory_id: str, user_id: str = Query(...)):
    """Delete a memory entry (enforces ownership via user_id)."""
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    _validate_uuid(memory_id)
    _validate_uuid(user_id)
    if not await db.delete_user_memory(memory_id, user_id):
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"status": "deleted"}


# --- Shared helpers for /chat and /chat/stream ---

def _select_model(request: ChatRequest) -> str:
    """Select model: explicit choice from user, or smart routing with tool override."""
    if request.model:
        logger.info("Model: %s (user selected)", request.model)
        return request.model
    model, reason = router.select_model(request.message)
    if (request.use_tools and settings.ROUTE_TOOLS_MODEL
            and model != settings.ROUTE_TOOLS_MODEL):
        logger.info("Model: %s → %s (auto — tools override)", model, settings.ROUTE_TOOLS_MODEL)
        return settings.ROUTE_TOOLS_MODEL
    logger.info("Model: %s (auto — %s)", model, reason)
    return model


async def _load_messages(request: ChatRequest, conversation_id: str) -> list[dict]:
    """Load conversation history from DB or use the request's inline history."""
    if request.conversation_id and db.is_available():
        stored = await db.get_messages(conversation_id)
        return [{"role": m["role"], "content": m["content"]} for m in stored]
    return list(request.history)


async def _persist_turn(
    request: ChatRequest, conversation_id: str, model: str,
    response_text: str, is_new: bool, messages: list[dict],
) -> None:
    """Save the conversation turn to DB and kick off background tasks."""
    if not db.is_available():
        return
    try:
        title = request.message[:80] if is_new else ""
        await db.upsert_conversation(conversation_id, model, title, request.user_id)
        await db.add_message(conversation_id, "user", request.message)
        await db.add_message(conversation_id, "assistant", response_text)
    except Exception as e:
        logger.warning("Failed to persist conversation: %s", e)

    if is_new:
        asyncio.create_task(
            _generate_title(conversation_id, request.message, response_text, model)
        )

    _maybe_extract_memories(request, messages, response_text, model)


async def _get_is_child(user_id: str | None) -> bool:
    """Look up the is_child flag for safety guardrails."""
    if not user_id or not db.is_available():
        return False
    try:
        user_record = await db.get_user_by_id(user_id)
        return bool(user_record and user_record.get("is_child", False))
    except Exception:
        return False


async def _retrieve_rag_context(message: str, user_id: str | None = None) -> str | None:
    """Embed the query and search Qdrant for relevant chunks."""
    if not vector_store.is_available():
        return None
    query_text = f"search_query: {message}"
    query_vectors = await client.embed([query_text])
    results = vector_store.search(query_vectors[0], limit=5, user_id=user_id)
    if results:
        parts = [f"[{r.get('source', 'unknown')}]\n{r['text']}" for r in results]
        return _RAG_SYSTEM_PROMPT.format(context="\n---\n".join(parts))
    return None


def _build_options(request: ChatRequest) -> dict:
    """Build the Ollama options dict from the request.

    Only includes non-None values — Ollama uses its defaults for anything omitted.
    """
    options: dict = {"temperature": request.temperature}
    for key in ("top_p", "top_k", "num_predict", "repeat_penalty", "seed", "num_ctx"):
        value = getattr(request, key)
        if value is not None:
            options[key] = value
    return options


def _maybe_extract_memories(
    request: ChatRequest, messages: list[dict], response_text: str, model: str
) -> None:
    """Fire-and-forget memory extraction every 6 turns."""
    if not request.user_id or not db.is_available():
        return
    turn_count = sum(1 for m in messages if m.get("role") in ("user", "assistant"))
    if turn_count >= 6 and turn_count % 6 == 0:
        extraction_messages = messages + [{"role": "assistant", "content": response_text}]
        asyncio.create_task(
            context.extract_memories(extraction_messages, client, model, request.user_id)
        )


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """Streaming chat endpoint — sends SSE events with status updates.

    Generation runs as an independent asyncio.Task so it completes and
    persists to the database even if the client disconnects mid-stream
    (fire-and-forget).  The SSE generator is a thin consumer that reads
    from a shared queue; dropping the connection does *not* cancel the
    generation task.
    """
    import json as _json
    from starlette.responses import StreamingResponse

    is_child = await _get_is_child(request.user_id)
    queue: asyncio.Queue = asyncio.Queue()
    disconnected = asyncio.Event()

    async def _run_generation():
        """Produce events onto *queue*. Runs as a background task."""
        async def _put(event: str, data: dict):
            # Skip status/token events when consumer is gone to avoid
            # unbounded queue growth.  Always enqueue done/error so
            # _persist_turn results are not lost.
            if disconnected.is_set() and event in ("status", "token"):
                return
            await queue.put({"event": event, "data": data})

        try:
            model = _select_model(request)
            conversation_id = request.conversation_id or str(uuid.uuid4())
            messages = await _load_messages(request, conversation_id)

            # RAG
            await _put("status", {"status": "preparing", "detail": "Building context..."})

            rag_context = None
            if request.use_rag:
                try:
                    await _put("status", {"status": "rag", "detail": "Searching documents..."})
                    rag_context = await _retrieve_rag_context(request.message, request.user_id)
                except Exception:
                    pass

            # System prompt (includes child safety if applicable)
            system_prompt = await context.build_system_prompt(
                user_id=request.user_id,
                user_system_prompt=request.system_prompt,
                rag_context=rag_context,
                use_tools=request.use_tools,
                is_child=is_child,
            )
            if system_prompt:
                messages.insert(0, {"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": request.message})

            # Summarize if needed
            if context.should_summarize(messages):
                await _put("status", {"status": "summarizing", "detail": "Compressing conversation history..."})
                messages = await context.summarize_conversation(messages, client, model)

            options = _build_options(request)

            await _put("status", {"status": "thinking", "detail": f"Asking {model}..."})

            tools_used = []
            response_text = ""

            plan = None
            if request.use_tools:
                # Tool rounds are non-streaming; final answer streams tokens
                async for event in client.chat_with_tools_stream(
                    model=model, messages=messages, options=options,
                    user_id=request.user_id,
                ):
                    if event["type"] == "status":
                        await _put("status", {"status": event["status"], "detail": event["detail"]})
                    elif event["type"] == "token":
                        response_text += event["text"]
                        await _put("token", {"text": event["text"]})
                    elif event["type"] == "done":
                        tools_used = event["tools_used"]
                        plan = event.get("plan")
                if tools_used:
                    logger.info("Tools used: %s", [t["name"] for t in tools_used])
            else:
                # Stream tokens directly from Ollama
                async for token in client.chat_stream(
                    model=model, messages=messages, options=options,
                ):
                    response_text += token
                    await _put("token", {"text": token})

            # Record trace for Weave (streaming methods aren't directly traced)
            await client._trace_streaming_chat(model, messages, options, response_text)

            is_new = not request.conversation_id
            await _persist_turn(request, conversation_id, model, response_text, is_new, messages)

            # Send final result
            await _put("done", {"response": response_text, "model": model, "conversation_id": conversation_id, "tools_used": tools_used, "plan": plan})

        except Exception as e:
            await _put("error", {"detail": str(e)})
        finally:
            await queue.put(None)  # sentinel — signals consumer to stop

    # Launch generation as an independent task (survives client disconnect)
    asyncio.create_task(_run_generation())

    async def _sse_consumer():
        """Yield SSE-formatted strings from the queue. If the client
        disconnects (GeneratorExit), the generation task keeps running."""
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                yield f"event: {event['event']}\ndata: {_json.dumps(event['data'])}\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            disconnected.set()  # tell _run_generation to stop queuing

    return StreamingResponse(_sse_consumer(), media_type="text/event-stream")


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    model = _select_model(request)
    conversation_id = request.conversation_id or str(uuid.uuid4())
    messages = await _load_messages(request, conversation_id)

    # RAG: retrieve relevant context (before building system prompt)
    rag_context = None
    if request.use_rag:
        try:
            rag_context = await _retrieve_rag_context(request.message, request.user_id)
            if rag_context:
                logger.info("RAG: injected context into prompt")
        except Exception as e:
            logger.warning("RAG search failed, proceeding without context: %s", e)

    is_child = await _get_is_child(request.user_id)

    # Build system prompt: safety + agent + memory + custom prompt + RAG
    system_prompt = await context.build_system_prompt(
        user_id=request.user_id,
        user_system_prompt=request.system_prompt,
        rag_context=rag_context,
        use_tools=request.use_tools,
        is_child=is_child,
    )
    if system_prompt:
        messages.insert(0, {"role": "system", "content": system_prompt})

    messages.append({"role": "user", "content": request.message})

    # Summarize if conversation is getting long (preserves early context)
    if context.should_summarize(messages):
        logger.info("Conversation approaching context limit — summarizing")
        messages = await context.summarize_conversation(messages, client, model)

    options = _build_options(request)

    # Call Ollama — with or without tool use
    tools_used = []
    try:
        if request.use_tools:
            response_text, tools_used = await client.chat_with_tools(
                model=model,
                messages=messages,
                options=options,
                user_id=request.user_id,
            )
            if tools_used:
                logger.info("Tools used: %s", [t["name"] for t in tools_used])
        else:
            response_text = await client.chat(
                model=model,
                messages=messages,
                options=options,
            )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama error: {e}")

    is_new = not request.conversation_id
    await _persist_turn(request, conversation_id, model, response_text, is_new, messages)

    return ChatResponse(
        response=response_text,
        model=model,
        conversation_id=conversation_id,
        tools_used=tools_used,
    )


async def _generate_title(
    conversation_id: str, user_message: str, assistant_response: str, model: str
) -> None:
    """Background task: ask the LLM for a short title and update the DB."""
    try:
        title = await client.generate_title(user_message, assistant_response, model)
        await db.update_conversation_title(conversation_id, title)
        logger.info("Generated title for %s: %s", conversation_id[:8], title)
    except Exception as e:
        logger.warning("Failed to generate title for %s: %s", conversation_id[:8], e)


# --- Document ingestion ---


@app.post("/ingest")
async def ingest_file(
    file: UploadFile,
    user_id: str | None = Form(None),
    is_private: bool = Form(False),
):
    """Upload a document, chunk it, embed chunks, and store in Qdrant."""
    if not vector_store.is_available():
        raise HTTPException(status_code=503, detail="Vector store not available")

    filename = file.filename or "unknown"
    content_bytes = await file.read()

    try:
        text = chunker.load_bytes(content_bytes, filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not text.strip():
        raise HTTPException(status_code=400, detail="Document is empty")

    chunks = chunker.chunk_text(text)
    if not chunks:
        raise HTTPException(status_code=400, detail="No chunks produced from document")

    prefixed_texts = [f"search_document: {c['text']}" for c in chunks]
    try:
        vectors = await client.embed(prefixed_texts)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Embedding failed: {e}")

    document_id = None
    if db.is_available():
        try:
            document_id = await db.add_document(filename, len(chunks), user_id, is_private)
        except Exception as e:
            logger.warning("Failed to record document in DB: %s", e)

    if not document_id:
        document_id = str(uuid.uuid4())

    vector_store.upsert_chunks(chunks, vectors, document_id, filename, user_id, is_private)

    logger.info("Ingested %s: %d chunks, doc_id=%s, private=%s", filename, len(chunks), document_id[:8], is_private)
    return {
        "document_id": document_id,
        "source": filename,
        "num_chunks": len(chunks),
        "is_private": is_private,
    }


@app.get("/documents")
async def list_documents(user_id: str | None = Query(None)):
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    documents = await db.list_documents(user_id=user_id)
    return {"documents": documents}


@app.delete("/documents/{document_id}")
async def delete_document(document_id: str, user_id: str | None = Query(None)):
    # Check ownership in Postgres FIRST — only delete vectors if allowed.
    if db.is_available():
        deleted = await db.delete_document(document_id, user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Document not found")

    if vector_store.is_available():
        try:
            vector_store.delete_by_document(document_id)
        except Exception as e:
            logger.warning("Failed to delete vectors from Qdrant: %s", e)

    return {"status": "deleted"}


# --- Conversation endpoints ---


@app.get("/conversations")
async def list_conversations(user_id: str | None = Query(None)):
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    if user_id:
        _validate_uuid(user_id)
    conversations = await db.list_conversations(user_id=user_id)
    return {"conversations": conversations}


@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    meta = await db.get_conversation(conversation_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = await db.get_messages(conversation_id)
    return {**meta, "messages": messages}


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    deleted = await db.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"status": "deleted"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.GATEWAY_HOST,
        port=settings.GATEWAY_PORT,
        reload=True,
    )
