import asyncio
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Add shared module to path (for local dev outside Docker)
_shared_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared", "python")
if os.path.isdir(_shared_path) and _shared_path not in sys.path:
    sys.path.insert(0, _shared_path)

from ai_lab_common.config import settings
from src import db
from src.ollama_client import OllamaClient

logger = logging.getLogger(__name__)

client: OllamaClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global client
    # --- Weave init ---
    try:
        import weave

        # Workaround: weave 0.52.x passes logging.info (function) instead of
        # logging.INFO (int) when configuring loggers during init.
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
        logger.warning("Failed to initialize Weave: %s — tracing disabled, gateway will serve requests without it.", e)

    # --- Database pool init ---
    try:
        await db.init_pool(settings.DATABASE_URL)
        logger.info("Database connected")
    except Exception as e:
        logger.warning("Failed to connect to database: %s — conversation persistence disabled.", e)

    client = OllamaClient(settings.OLLAMA_HOST)
    yield
    await client.close()
    await db.close_pool()


app = FastAPI(title="AI Lab - LLM Gateway", lifespan=lifespan)


# --- Models ---


class ChatRequest(BaseModel):
    message: str
    model: str | None = None
    temperature: float = 0.7
    history: list[dict] = []
    conversation_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    model: str
    conversation_id: str


# --- Endpoints ---


@app.get("/health")
async def health():
    return {"status": "ok", "database": db.is_available()}


@app.get("/models")
async def list_models():
    try:
        models = await client.list_models()
        return {"models": [m["name"] for m in models]}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to reach Ollama: {e}")


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    model = request.model or settings.OLLAMA_MODEL
    conversation_id = request.conversation_id or str(uuid.uuid4())

    # Build message history
    if request.conversation_id and db.is_available():
        # Existing conversation — load history from DB (ignore client-sent history)
        stored = await db.get_messages(conversation_id)
        messages = [{"role": m["role"], "content": m["content"]} for m in stored]
    else:
        # New conversation or DB unavailable — use client-sent history
        messages = list(request.history)

    messages.append({"role": "user", "content": request.message})

    # Call Ollama
    try:
        response_text = await client.chat(
            model=model,
            messages=messages,
            temperature=request.temperature,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama error: {e}")

    # Persist to DB if available
    is_new_conversation = not request.conversation_id
    if db.is_available():
        try:
            # For new conversations, use a placeholder title; LLM will generate a better one
            title = request.message[:80] if is_new_conversation else ""
            await db.upsert_conversation(conversation_id, model, title)
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


@app.get("/conversations")
async def list_conversations():
    if not db.is_available():
        raise HTTPException(status_code=503, detail="Database not available")
    conversations = await db.list_conversations()
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
