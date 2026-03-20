import asyncio
import logging
from functools import partial

import httpx

from ai_lab_common.config import settings
from src import tools

logger = logging.getLogger(__name__)

# Conditional weave import — no-op decorator when disabled
if settings.WEAVE_ENABLED:
    try:
        import weave
        _trace = weave.op()
    except Exception:
        _trace = lambda fn: fn  # noqa: E731
else:
    _trace = lambda fn: fn  # noqa: E731


class OllamaClient:
    def __init__(self, base_url: str, timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.http = httpx.AsyncClient(base_url=self.base_url, timeout=timeout)

    @_trace
    async def chat(self, model: str, messages: list[dict], options: dict | None = None) -> str:
        """Send a chat completion request to Ollama and return the response text."""
        response = await self.http.post(
            "/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "options": options or {},
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["message"]["content"]

    @_trace
    async def chat_with_tools(
        self,
        model: str,
        messages: list[dict],
        options: dict | None = None,
        max_tool_rounds: int = 5,
    ) -> tuple[str, list[dict]]:
        """Chat with tool use support.

        Sends available tools to the model. If the model returns tool_calls,
        executes them and feeds results back — repeating until the model
        produces a final text response or we hit max_tool_rounds.

        Returns (response_text, tools_used) where tools_used is a list of
        {"name": str, "arguments": dict, "result": str} for each tool call.
        """
        tool_schemas = tools.get_tool_schemas()
        tools_used = []

        for round_num in range(max_tool_rounds):
            response = await self.http.post(
                "/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "options": options or {},
                    "tools": tool_schemas,
                },
            )
            response.raise_for_status()
            data = response.json()
            msg = data["message"]

            # If no tool calls, the model produced a final text response
            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                return msg.get("content", ""), tools_used

            # Model wants to call tools — execute each one
            logger.info("Tool round %d: %d call(s)", round_num + 1, len(tool_calls))

            # Add the assistant's tool_calls message to history (verbatim)
            messages.append(msg)

            loop = asyncio.get_running_loop()
            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                fn_args = tc["function"]["arguments"]

                # Run tools in threadpool so sync I/O (e.g. web_search)
                # doesn't block the async event loop
                result = await loop.run_in_executor(
                    None, partial(tools.execute_tool, fn_name, fn_args)
                )
                tools_used.append({
                    "name": fn_name,
                    "arguments": fn_args,
                    "result": result,
                })

                # Feed tool result back to the model
                messages.append({
                    "role": "tool",
                    "content": result,
                })

        # Exhausted max rounds — get a final response without tools
        logger.warning("Hit max tool rounds (%d), requesting final response", max_tool_rounds)
        response = await self.http.post(
            "/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "options": options or {},
            },
        )
        response.raise_for_status()
        return response.json()["message"]["content"], tools_used

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

    @_trace
    async def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        """Embed one or more texts via Ollama /api/embed."""
        response = await self.http.post(
            "/api/embed",
            json={
                "model": model or settings.OLLAMA_EMBED_MODEL,
                "input": texts,
            },
        )
        response.raise_for_status()
        return response.json()["embeddings"]

    async def list_models(self) -> list[dict]:
        """List available models on the Ollama instance."""
        response = await self.http.get("/api/tags")
        response.raise_for_status()
        data = response.json()
        return data.get("models", [])

    async def close(self):
        await self.http.aclose()
