import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Add shared module to path (for local dev outside Docker)
_shared_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "shared", "python")
if os.path.isdir(_shared_path) and _shared_path not in sys.path:
    sys.path.insert(0, _shared_path)

from ai_lab_common.config import settings
from src.ollama_client import OllamaClient

logger = logging.getLogger(__name__)

client: OllamaClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global client
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
    client = OllamaClient(settings.OLLAMA_HOST)
    yield
    await client.close()


app = FastAPI(title="AI Lab - LLM Gateway", lifespan=lifespan)


class ChatRequest(BaseModel):
    message: str
    model: str | None = None
    temperature: float = 0.7
    history: list[dict] = []


class ChatResponse(BaseModel):
    response: str
    model: str


@app.get("/health")
async def health():
    return {"status": "ok"}


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
    messages = list(request.history)
    messages.append({"role": "user", "content": request.message})

    try:
        response_text = await client.chat(
            model=model,
            messages=messages,
            temperature=request.temperature,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Ollama error: {e}")

    return ChatResponse(response=response_text, model=model)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.GATEWAY_HOST,
        port=settings.GATEWAY_PORT,
        reload=True,
    )
