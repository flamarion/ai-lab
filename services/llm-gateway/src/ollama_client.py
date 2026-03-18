import httpx
import weave


class OllamaClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.http = httpx.AsyncClient(base_url=self.base_url, timeout=120.0)

    @weave.op()
    async def chat(self, model: str, messages: list[dict], temperature: float = 0.7) -> str:
        """Send a chat completion request to Ollama and return the response text."""
        response = await self.http.post(
            "/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature},
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["message"]["content"]

    async def generate_title(self, user_message: str, assistant_response: str, model: str) -> str:
        """Ask the LLM to produce a short conversation title."""
        messages = [
            {
                "role": "system",
                "content": (
                    "Generate a short title (3-6 words) that summarizes this conversation. "
                    "Reply with ONLY the title, no quotes, no punctuation at the end."
                ),
            },
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": assistant_response},
            {"role": "user", "content": "Now generate a short title for this conversation."},
        ]
        response = await self.http.post(
            "/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.3},
            },
        )
        response.raise_for_status()
        title = response.json()["message"]["content"].strip().strip("\"'")
        return title[:80]

    async def list_models(self) -> list[dict]:
        """List available models on the Ollama instance."""
        response = await self.http.get("/api/tags")
        response.raise_for_status()
        data = response.json()
        return data.get("models", [])

    async def close(self):
        await self.http.aclose()
