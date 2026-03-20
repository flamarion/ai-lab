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

Each server is launched as a subprocess using stdio transport. Tools from
all servers are merged with local tools from tools.py.
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

# Config path: env var override or default to mcp_servers.json next to the src/ dir
_CONFIG_PATH = Path(
    os.getenv("MCP_CONFIG_PATH", Path(__file__).resolve().parent.parent / "mcp_servers.json")
)

# Timeout for connecting to each MCP server (seconds)
_CONNECT_TIMEOUT = 30

# Minimal env vars passed to MCP subprocesses (avoid leaking secrets)
_ENV_ALLOWLIST = {"PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "TMPDIR"}


class MCPClientManager:
    """Manages connections to multiple MCP servers.

    On startup, reads mcp_servers.json and connects to each configured server.
    Exposes their tools in Ollama-compatible format and routes tool calls
    to the correct server. All state mutations are guarded by an asyncio.Lock.
    """

    def __init__(self):
        self._exit_stack = AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}
        self._tools: dict[str, tuple[str, dict]] = {}
        self._lock = asyncio.Lock()

    async def start(self):
        """Connect to all configured MCP servers."""
        config = self._load_config()
        if not config:
            logger.info("No MCP servers configured")
            return

        async with self._lock:
            for name, server_config in config.items():
                try:
                    await asyncio.wait_for(
                        self._connect_stdio(name, server_config),
                        timeout=_CONNECT_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    logger.warning("MCP server '%s' timed out after %ds, skipping", name, _CONNECT_TIMEOUT)
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
        async with self._lock:
            await self._exit_stack.aclose()
            self._exit_stack = AsyncExitStack()
            self._sessions.clear()
            self._tools.clear()

    async def reload(self):
        """Reconnect to all MCP servers (e.g. after config change)."""
        logger.info("Reloading MCP servers...")
        await self.stop()
        await self.start()

    def get_config(self) -> dict:
        """Return the current MCP server config."""
        return self._load_config()

    def save_config(self, servers: dict):
        """Write MCP server config to mcp_servers.json."""
        data = {"mcpServers": servers}
        with open(_CONFIG_PATH, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

    def add_server(self, name: str, command: str, args: list[str], env: dict | None = None):
        """Add a server to the config file (does not connect — call reload())."""
        config = self._load_config()
        config[name] = {"command": command, "args": args, "env": env or {}}
        self.save_config(config)

    def remove_server(self, name: str) -> bool:
        """Remove a server from the config file (does not disconnect — call reload())."""
        config = self._load_config()
        if name not in config:
            return False
        del config[name]
        self.save_config(config)
        return True

    def get_tool_schemas(self) -> list[dict]:
        """Return Ollama-compatible tool schemas for all MCP tools."""
        return [schema for _, schema in self._tools.values()]

    def get_tool_names(self) -> list[str]:
        """Return names of all available MCP tools."""
        return list(self._tools.keys())

    def list_tools(self) -> list[dict]:
        """Return tool info dicts for the /tools API endpoint."""
        return [
            {
                "name": name,
                "description": schema["function"]["description"],
                "source": "mcp",
            }
            for name, (_, schema) in self._tools.items()
        ]

    def list_servers(self) -> list[dict]:
        """Return server info dicts for the /mcp/servers API endpoint."""
        config = self._load_config()
        connected = set(self._sessions.keys())
        return [
            {
                "name": name,
                "command": cfg.get("command", ""),
                "args": cfg.get("args", []),
                "connected": name in connected,
                "tools": [
                    t_name for t_name, (s_name, _) in self._tools.items()
                    if s_name == name
                ],
            }
            for name, cfg in config.items()
        ]

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
            logger.info("MCP config not found at %s", _CONFIG_PATH)
            return {}
        try:
            with open(_CONFIG_PATH) as f:
                data = json.load(f)
            return data.get("mcpServers", {})
        except Exception as e:
            logger.warning("Failed to load MCP config from %s: %s", _CONFIG_PATH, e)
            return {}

    def _build_env(self, server_env: dict | None) -> dict:
        """Build a minimal environment for MCP subprocesses.

        Only passes allowlisted vars from the host + server-specific env vars.
        Avoids leaking secrets (DB URLs, API keys) to MCP server processes.
        """
        safe_env = {k: v for k, v in os.environ.items() if k in _ENV_ALLOWLIST}
        if server_env:
            safe_env.update(server_env)
        return safe_env

    async def _connect_stdio(self, name: str, config: dict):
        """Connect to an MCP server via stdio transport."""
        command = config.get("command")
        args = config.get("args", [])
        env = config.get("env")

        if not command:
            logger.warning("MCP server '%s' has no command, skipping", name)
            return

        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=self._build_env(env),
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

        # Discover tools — detect and warn on name collisions
        from src import tools as local_tools
        local_names = set(local_tools.TOOL_REGISTRY.keys())

        response = await session.list_tools()
        for tool in response.tools:
            if tool.name in local_names:
                logger.warning(
                    "MCP tool '%s' from '%s' conflicts with local tool — local tool takes priority",
                    tool.name, name,
                )
                continue
            if tool.name in self._tools:
                prev_server = self._tools[tool.name][0]
                logger.warning(
                    "MCP tool '%s' from '%s' conflicts with '%s' — keeping first registration",
                    tool.name, name, prev_server,
                )
                continue
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
