import os


class Settings:
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://192.168.1.178:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "mistral:7b")
    ROUTE_CODE_MODEL: str = os.getenv("ROUTE_CODE_MODEL", "qwen3.5:27b")
    ROUTE_DEFAULT_MODEL: str = os.getenv("ROUTE_DEFAULT_MODEL", "mistral:7b")
    ROUTE_TOOLS_MODEL: str = os.getenv("ROUTE_TOOLS_MODEL", "qwen3.5:27b")
    ROUTE_VISION_MODEL: str = os.getenv("ROUTE_VISION_MODEL", "gemma3:12b")
    GATEWAY_HOST: str = os.getenv("GATEWAY_HOST", "0.0.0.0")
    GATEWAY_PORT: int = int(os.getenv("GATEWAY_PORT", "8000"))
    GATEWAY_URL: str = os.getenv("GATEWAY_URL", "http://localhost/api")
    OLLAMA_EMBED_MODEL: str = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text-v2-moe")
    WEAVE_ENABLED: bool = os.getenv("WEAVE_ENABLED", "true").strip().lower() in ("true", "1", "yes")
    WANDB_PROJECT: str = os.getenv("WANDB_PROJECT", "ai-lab")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://ailab:ailab_dev@192.168.1.202:5432/ailab")
    QDRANT_HOST: str = os.getenv("QDRANT_HOST", "192.168.1.202")
    QDRANT_PORT: int = int(os.getenv("QDRANT_PORT", "6333"))
    QDRANT_COLLECTION: str = os.getenv("QDRANT_COLLECTION", "ai-lab-docs")

    # Embedding
    EMBED_DIMENSION: int = int(os.getenv("EMBED_DIMENSION", "768"))

    # Context management
    CONTEXT_LIMIT: int = int(os.getenv("CONTEXT_LIMIT", "28000"))

    # SearXNG (web search)
    SEARXNG_URL: str = os.getenv("SEARXNG_URL", "http://searxng:8080")


settings = Settings()
