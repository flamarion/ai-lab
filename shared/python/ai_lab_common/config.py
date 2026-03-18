import os


class Settings:
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://192.168.1.178:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "mistral:7b")
    ROUTE_CODE_MODEL: str = os.getenv("ROUTE_CODE_MODEL", "qwen3.5:latest")
    ROUTE_DEFAULT_MODEL: str = os.getenv("ROUTE_DEFAULT_MODEL", "mistral:7b")
    GATEWAY_HOST: str = os.getenv("GATEWAY_HOST", "0.0.0.0")
    GATEWAY_PORT: int = int(os.getenv("GATEWAY_PORT", "8000"))
    WANDB_PROJECT: str = os.getenv("WANDB_PROJECT", "ai-lab")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://ailab:ailab_dev@192.168.1.202:5432/ailab")


settings = Settings()
