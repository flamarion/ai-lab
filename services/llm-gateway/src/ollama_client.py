import asyncio
import json
import logging
from collections.abc import AsyncIterator
from functools import partial

import httpx

from ai_lab_common.config import settings
from src import tools
from src.mcp_client import mcp_manager

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
    def __init__(self, base_url: str, timeout: float | None = None):
        self.base_url = base_url.rstrip("/")
        # No timeout — 27B model cold starts (loading across 2 GPUs) and
        # long generations on 32k context can take several minutes.
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
    async def _trace_streaming_chat(
        self, model: str, messages: list[dict], options: dict | None, response: str
    ) -> str:
        """Record a streaming chat for Weave tracing. Called after all tokens are collected."""
        return response

    async def chat_stream(
        self, model: str, messages: list[dict], options: dict | None = None
    ) -> AsyncIterator[str]:
        """Stream chat tokens from Ollama. Yields each text chunk as it arrives."""
        async with self.http.stream(
            "POST",
            "/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": True,
                "options": options or {},
            },
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                chunk = json.loads(line)
                token = chunk.get("message", {}).get("content", "")
                if token:
                    yield token
                if chunk.get("done"):
                    break

    @_trace
    async def chat_with_tools(
        self,
        model: str,
        messages: list[dict],
        options: dict | None = None,
        max_tool_rounds: int = 5,
        on_status=None,
        user_id: str | None = None,
        allowed_tools: list[str] | None = None,
    ) -> tuple[str, list[dict]]:
        """Chat with tool use support.

        Sends available tools to the model. If the model returns tool_calls,
        executes them and feeds results back — repeating until the model
        produces a final text response or we hit max_tool_rounds.

        on_status: optional async callback(status: str, detail: str) for
        real-time progress reporting (SSE streaming).

        Returns (response_text, tools_used) where tools_used is a list of
        {"name": str, "arguments": dict, "result": str} for each tool call.
        """
        async def _status(status: str, detail: str = ""):
            if on_status:
                await on_status(status, detail)

        # Merge local tools + MCP tools into one list for the model
        tool_schemas = tools.get_tool_schemas() + mcp_manager.get_tool_schemas()
        if allowed_tools:
            tool_schemas = [s for s in tool_schemas if s["function"]["name"] in allowed_tools]
        tools_used = []

        for round_num in range(max_tool_rounds):
            await _status("thinking", f"Round {round_num + 1}" if round_num > 0 else "Thinking...")

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

            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                fn_args = tc["function"]["arguments"]

                await _status("tool_call", f"Using {fn_name}...")

                # Route to MCP or local tool
                if mcp_manager.has_tool(fn_name):
                    result = await mcp_manager.call_tool(fn_name, fn_args)
                else:
                    # Run local tools in threadpool (they may do sync I/O)
                    loop = asyncio.get_running_loop()
                    result = await loop.run_in_executor(
                        None, partial(tools.execute_tool, fn_name, fn_args, user_id)
                    )

                await _status("tool_result", f"{fn_name} completed")

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

    async def chat_with_tools_stream(
        self,
        model: str,
        messages: list[dict],
        options: dict | None = None,
        max_tool_rounds: int = 5,
        user_id: str | None = None,
        allowed_tools: list[str] | None = None,
    ) -> AsyncIterator[dict]:
        """Streaming tool use. Yields dicts:
        {"type": "status", "status": str, "detail": str}
        {"type": "token", "text": str}
        {"type": "done", "tools_used": list}
        Tool rounds are non-streaming; the final answer streams tokens.
        """
        tool_schemas = tools.get_tool_schemas() + mcp_manager.get_tool_schemas()
        if allowed_tools:
            tool_schemas = [s for s in tool_schemas if s["function"]["name"] in allowed_tools]
        tools_used = []

        for round_num in range(max_tool_rounds):
            yield {"type": "status", "status": "thinking",
                   "detail": f"Round {round_num + 1}" if round_num > 0 else "Thinking..."}

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

            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                # Reuse already-generated content — re-querying would double
                # latency and produce a non-deterministic second answer.
                content = msg.get("content", "")
                if content:
                    yield {"type": "token", "text": content}
                yield {"type": "done", "tools_used": tools_used}
                return

            logger.info("Tool round %d: %d call(s)", round_num + 1, len(tool_calls))
            messages.append(msg)

            for tc in tool_calls:
                fn_name = tc["function"]["name"]
                fn_args = tc["function"]["arguments"]

                yield {"type": "status", "status": "tool_call", "detail": f"Using {fn_name}..."}

                if mcp_manager.has_tool(fn_name):
                    result = await mcp_manager.call_tool(fn_name, fn_args)
                else:
                    loop = asyncio.get_running_loop()
                    result = await loop.run_in_executor(
                        None, partial(tools.execute_tool, fn_name, fn_args, user_id)
                    )

                yield {"type": "status", "status": "tool_result", "detail": f"{fn_name} completed"}

                tools_used.append({
                    "name": fn_name,
                    "arguments": fn_args,
                    "result": result,
                })
                messages.append({"role": "tool", "content": result})

        # Exhausted max rounds — stream final response without tools
        logger.warning("Hit max tool rounds (%d), requesting final response", max_tool_rounds)
        full_text = ""
        async for token in self.chat_stream(model, messages, options):
            yield {"type": "token", "text": token}
            full_text += token
        yield {"type": "done", "tools_used": tools_used}

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
