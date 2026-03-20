"""MCP Client Manager — connects to MCP servers and exposes their tools.

MCP (Model Context Protocol) is a standard for tool discovery and execution.
Instead of hardcoding tools in tools.py, MCP servers provide tools via a
standard protocol. This module manages connections to MCP servers and
translates their tools into Ollama-compatible schemas.

Servers are configured via mcp_servers.json (same format as Claude Desktop):

    {
        "mcpServers": {
            "fetch": {
                "command": "python",
                "args": ["-m", "mcp_server_fetch"],
                "env": {}
            }
        }
    }

Each server is launched as a subprocess (stdio transport) or connected
via HTTP (streamable_http transport). Tools from all servers are merged
with local tools from tools.py.
"""

import asyncio
import json
import logging
import os
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

# Path to MCP server config — same format as Claude Desktop
_CONFIG_PATH = Path(__file__).resolve().parent.parent / "mcp_servers.json"


class MCPClientManager:
    """Manages connections to multiple MCP servers.

    On startup, reads mcp_servers.json and connects to each configured server.
    Exposes their tools in Ollama-compatible format and routes tool calls
    to the correct server.
    """

    def __init__(self):
        self._exit_stack = AsyncExitStack()
        # server_name → ClientSession
        self._sessions: dict[str, ClientSession] = {}
        # tool_name → (server_name, tool_schema)
        self._tools: dict[str, tuple[str, dict]] = {}

    async def start(self):
        """Connect to all configured MCP servers."""
        config = self._load_config()
        if not config:
            logger.info("No MCP servers configured")
            return

        for name, server_config in config.items():
            try:
                await self._connect_stdio(name, server_config)
            except Exception as e:
                logger.warning("Failed to connect to MCP server '%s': %s", name, e)

        if self._tools:
            logger.info(
                "MCP ready: %d server(s), %d tool(s): %s",
                len(self._sessions),
                len(self._tools),
                list(self._tools.keys()),
            )

    async def stop(self):
        """Disconnect from all MCP servers."""
        await self._exit_stack.aclose()
        self._sessions.clear()
        self._tools.clear()

    def get_tool_schemas(self) -> list[dict]:
        """Return Ollama-compatible tool schemas for all MCP tools."""
        schemas = []
        for tool_name, (_, schema) in self._tools.items():
            schemas.append(schema)
        return schemas

    def get_tool_names(self) -> list[str]:
        """Return names of all available MCP tools."""
        return list(self._tools.keys())

    def has_tool(self, name: str) -> bool:
        """Check if a tool is provided by an MCP server."""
        return name in self._tools

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Execute a tool on its MCP server and return the result as a string."""
        if name not in self._tools:
            return f"Error: MCP tool '{name}' not found"

        server_name, _ = self._tools[name]
        session = self._sessions.get(server_name)
        if not session:
            return f"Error: MCP server '{server_name}' not connected"

        try:
            result = await session.call_tool(name, arguments=arguments)
            # Collect all text content from the result
            parts = []
            for item in result.content:
                if hasattr(item, "text"):
                    parts.append(item.text)
            text = "\n".join(parts) if parts else "No output"
            logger.info("MCP tool %s(%s) via %s → %s", name, arguments, server_name, text[:100])
            return text
        except Exception as e:
            logger.error("MCP tool %s failed: %s", name, e)
            return f"Error calling {name}: {e}"

    def _load_config(self) -> dict:
        """Load MCP server config from mcp_servers.json."""
        if not _CONFIG_PATH.exists():
            return {}
        try:
            with open(_CONFIG_PATH) as f:
                data = json.load(f)
            return data.get("mcpServers", {})
        except Exception as e:
            logger.warning("Failed to load MCP config from %s: %s", _CONFIG_PATH, e)
            return {}

    async def _connect_stdio(self, name: str, config: dict):
        """Connect to an MCP server via stdio transport."""
        command = config.get("command")
        args = config.get("args", [])
        env = config.get("env")

        if not command:
            logger.warning("MCP server '%s' has no command, skipping", name)
            return

        # Merge env with current environment (MCP servers often need PATH etc.)
        full_env = {**os.environ}
        if env:
            full_env.update(env)

        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=full_env,
        )

        logger.info("Connecting to MCP server '%s': %s %s", name, command, " ".join(args))

        transport = await self._exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        read, write = transport
        session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await session.initialize()

        self._sessions[name] = session

        # Discover tools and convert to Ollama-compatible schemas
        response = await session.list_tools()
        for tool in response.tools:
            ollama_schema = self._to_ollama_schema(tool)
            self._tools[tool.name] = (name, ollama_schema)
            logger.info("  Registered MCP tool: %s (%s)", tool.name, tool.description[:60] if tool.description else "no description")

    @staticmethod
    def _to_ollama_schema(tool) -> dict:
        """Convert an MCP tool definition to Ollama's tool schema format."""
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema or {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        }


# Singleton instance
mcp_manager = MCPClientManager()
