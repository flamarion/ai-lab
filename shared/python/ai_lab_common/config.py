import os


class Settings:
    OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://192.168.1.178:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "mistral:latest")
    GATEWAY_HOST: str = os.getenv("GATEWAY_HOST", "0.0.0.0")
    GATEWAY_PORT: int = int(os.getenv("GATEWAY_PORT", "8000"))
    WANDB_PROJECT: str = os.getenv("WANDB_PROJECT", "ai-lab")


settings = Settings()
