import asyncio
import logging
import os
import re
import sys
import uuid
from contextlib import asynccontextmanager

import bcrypt
from fastapi import FastAPI, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

# Add shared module to path (for local dev outside Docker)
_shared_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared", "python")
if os.path.isdir(_shared_path) and _shared_path not in sys.path:
    sys.path.insert(0, _shared_path)

from ai_lab_common.config import settings
from src import chunker, db, migrations, router, vector_store
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
    # --- Weave init ---
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

    # --- Database pool init ---
    try:
        await db.init_pool(settings.DATABASE_URL)
        logger.info("Database connected")
    except Exception as e:
        logger.warning("Failed to connect to database: %s — persistence disabled.", e)

    # --- Run migrations ---
    if db.is_available():
        try:
            await migrations.run_migrations(db.get_pool())
        except Exception as e:
            logger.warning("Migration failed: %s — schema may be incomplete.", e)

    # --- Qdrant init ---
    try:
        vector_store.init_store()
        logger.info("Qdrant connected")
    except Exception as e:
        logger.warning("Failed to connect to Qdrant: %s — RAG disabled.", e)

    client = OllamaClient(settings.OLLAMA_HOST)
    yield
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
    num_predict: int | None = None
    system_prompt: str | None = None
    use_rag: bool = False
    history: list[dict] = []
    conversation_id: str | None = None
    user_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    model: str
    conversation_id: str


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
        "preferences": user["preferences"],
    }


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

    # Verify current PIN by looking up the user
    _validate_uuid(request.user_id)
    users = await db.list_users()
    target = next((u for u in users if u["id"] == request.user_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    user = await db.get_user_by_username(target["username"])
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
    users = await db.list_users()
    admin = next((u for u in users if u["id"] == admin_user_id), None)
    if not admin or not admin.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return admin


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


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    # Model selection: explicit choice from user, or smart routing
    if request.model:
        model = request.model
        logger.info("Model: %s (user selected)", model)
    else:
        model, reason = router.select_model(request.message)
        logger.info("Model: %s (auto — %s)", model, reason)

    conversation_id = request.conversation_id or str(uuid.uuid4())

    # Build message history
    if request.conversation_id and db.is_available():
        stored = await db.get_messages(conversation_id)
        messages = [{"role": m["role"], "content": m["content"]} for m in stored]
    else:
        messages = list(request.history)

    # Inject system prompt if provided
    if request.system_prompt and request.system_prompt.strip():
        messages.insert(0, {"role": "system", "content": request.system_prompt.strip()})

    # RAG: retrieve relevant context and inject into the prompt
    if request.use_rag and vector_store.is_available():
        try:
            query_text = f"search_query: {request.message}"
            query_vectors = await client.embed([query_text])
            results = vector_store.search(query_vectors[0], limit=5)

            if results:
                context_parts = []
                for r in results:
                    source = r.get("source", "unknown")
                    context_parts.append(f"[{source}]\n{r['text']}")
                context = "\n---\n".join(context_parts)

                rag_system = _RAG_SYSTEM_PROMPT.format(context=context)
                messages.insert(0, {"role": "system", "content": rag_system})
                logger.info("RAG: injected %d chunks into prompt", len(results))
            else:
                logger.info("RAG: no relevant chunks found")
        except Exception as e:
            logger.warning("RAG search failed, proceeding without context: %s", e)

    messages.append({"role": "user", "content": request.message})

    # Build Ollama options (only include non-default values)
    options: dict = {"temperature": request.temperature}
    if request.top_p is not None:
        options["top_p"] = request.top_p
    if request.num_predict is not None:
        options["num_predict"] = request.num_predict

    # Call Ollama
    try:
        response_text = await client.chat(
            model=model,
            messages=messages,
            options=options,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama error: {e}")

    # Persist to DB if available
    is_new_conversation = not request.conversation_id
    if db.is_available():
        try:
            title = request.message[:80] if is_new_conversation else ""
            await db.upsert_conversation(conversation_id, model, title, request.user_id)
            await db.add_message(conversation_id, "user", request.message)
            await db.add_message(conversation_id, "assistant", response_text)
        except Exception as e:
            logger.warning("Failed to persist conversation: %s", e)

    # Generate a smart title in the background for new conversations
    if is_new_conversation and db.is_available():
        asyncio.create_task(
            _generate_title(conversation_id, request.message, response_text, model)
        )

    return ChatResponse(response=response_text, model=model, conversation_id=conversation_id)


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
async def ingest_file(file: UploadFile):
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
            document_id = await db.add_document(filename, len(chunks))
        except Exception as e:
            logger.warning("Failed to record document in DB: %s", e)

    if not document_id:
        document_id = str(uuid.uuid4())

    vector_store.upsert_chunks(chunks, vectors, document_id, filename)

    logger.info("Ingested %s: %d chunks, doc_id=%s", filename, len(chunks), document_id[:8])
    return {
        "document_id": document_id,
        "source": filename,
        "num_chunks": len(chunks),
    }


@app.get("/documents")
async def list_documents():
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    documents = await db.list_documents()
    return {"documents": documents}


@app.delete("/documents/{document_id}")
async def delete_document(document_id: str):
    if vector_store.is_available():
        try:
            vector_store.delete_by_document(document_id)
        except Exception as e:
            logger.warning("Failed to delete vectors from Qdrant: %s", e)

    if db.is_available():
        deleted = await db.delete_document(document_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Document not found")

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
