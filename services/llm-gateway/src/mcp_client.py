"""MCP Client Manager — connects to MCP servers and exposes their tools.

MCP (Model Context Protocol) is a standard for tool discovery and execution.
Instead of hardcoding tools in tools.py, MCP servers provide tools via a
standard protocol. This module manages connections to MCP servers and
translates their tools into Ollama-compatible schemas.

Servers are configured via mcp_servers.json (same format as Claude Desktop / Cursor):

    Stdio transport (local subprocess):
    {
        "mcpServers": {
            "fetch": {
                "command": "python",
                "args": ["-m", "mcp_server_fetch"]
            }
        }
    }

    HTTP transport (remote server):
    {
        "mcpServers": {
            "wandb": {
                "transport": "http",
                "url": "https://mcp.withwandb.com/mcp",
                "headers": {
                    "Authorization": "Bearer ${WANDB_API_KEY}"
                }
            }
        }
    }

    Use ${SECRET_NAME} in env/headers to reference secrets stored in the DB.
"""

import asyncio
import json
import logging
import os
import re
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

# Pattern for ${SECRET_NAME} substitution
_SECRET_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class MCPClientManager:
    """Manages connections to multiple MCP servers.

    Supports stdio (local subprocess) and HTTP (remote) transports.
    Secrets from the DB can be referenced via ${SECRET_NAME} in configs.
    """

    def __init__(self):
        self._exit_stack = AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}
        self._tools: dict[str, tuple[str, dict]] = {}
        self._lock = asyncio.Lock()
        # Cache of secrets for substitution (loaded on start/reload)
        self._secrets: dict[str, str] = {}

    async def start(self):
        """Connect to all configured MCP servers."""
        config = self._load_config()
        if not config:
            logger.info("No MCP servers configured")
            return

        # Load secrets for ${...} substitution
        await self._load_secrets()

        async with self._lock:
            for name, server_config in config.items():
                try:
                    await asyncio.wait_for(
                        self._connect_server(name, server_config),
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
            old_stack = self._exit_stack
            self._exit_stack = AsyncExitStack()
            self._sessions.clear()
            self._tools.clear()
            # Try to close gracefully. This can fail with RuntimeError when
            # called from a different task than the one that opened the
            # connections (anyio TaskGroup affinity). Safe to ignore — old
            # subprocesses are cleaned up on container restart.
            try:
                await old_stack.aclose()
            except RuntimeError:
                logger.warning("Could not cleanly close MCP connections (cross-task cleanup)")

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

    def add_server_config(self, name: str, config: dict):
        """Add a server config (full JSON object) to the config file."""
        all_config = self._load_config()
        all_config[name] = config
        self.save_config(all_config)

    def remove_server(self, name: str) -> bool:
        """Remove a server from the config file."""
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
        results = []
        for name, cfg in config.items():
            transport = cfg.get("transport", "stdio")
            info = {
                "name": name,
                "transport": transport,
                "connected": name in connected,
                "tools": [
                    t_name for t_name, (s_name, _) in self._tools.items()
                    if s_name == name
                ],
            }
            if transport == "http":
                info["url"] = cfg.get("url", "")
            else:
                info["command"] = cfg.get("command", "")
                info["args"] = cfg.get("args", [])
            results.append(info)
        return results

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

    # --- Internal methods ---

    def _substitute_secrets(self, value: str) -> str:
        """Replace ${SECRET_NAME} placeholders with values from the secrets store."""
        def _replace(match):
            key = match.group(1)
            if key in self._secrets:
                return self._secrets[key]
            logger.warning("Secret '${%s}' referenced but not found in secrets store", key)
            return match.group(0)  # leave as-is if not found
        return _SECRET_PATTERN.sub(_replace, value)

    def _substitute_dict(self, d: dict) -> dict:
        """Recursively substitute ${SECRET_NAME} in all string values of a dict."""
        result = {}
        for k, v in d.items():
            if isinstance(v, str):
                result[k] = self._substitute_secrets(v)
            elif isinstance(v, dict):
                result[k] = self._substitute_dict(v)
            elif isinstance(v, list):
                result[k] = [
                    self._substitute_secrets(item) if isinstance(item, str) else item
                    for item in v
                ]
            else:
                result[k] = v
        return result

    async def _load_secrets(self):
        """Load all secrets from the DB for substitution."""
        try:
            from src import db
            if db.is_available():
                self._secrets = await db.get_all_secrets()
                if self._secrets:
                    logger.info("Loaded %d secret(s) for MCP config substitution", len(self._secrets))
        except Exception as e:
            logger.warning("Could not load secrets: %s", e)
            self._secrets = {}

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

    async def _connect_server(self, name: str, config: dict):
        """Connect to an MCP server — dispatches to stdio or HTTP transport."""
        transport = config.get("transport", "stdio")
        if transport == "http":
            await self._connect_http(name, config)
        else:
            await self._connect_stdio(name, config)

    def _build_env(self, server_env: dict | None) -> dict:
        """Build a minimal environment for MCP subprocesses.

        All values are cast to str (subprocess env must be strings).
        """
        safe_env = {k: v for k, v in os.environ.items() if k in _ENV_ALLOWLIST}
        if server_env:
            for k, v in server_env.items():
                safe_env[k] = self._substitute_secrets(str(v))
        return safe_env

    async def _connect_stdio(self, name: str, config: dict):
        """Connect to an MCP server via stdio transport."""
        command = config.get("command")
        args = config.get("args", [])
        env = config.get("env")

        if not command:
            logger.warning("MCP server '%s' has no command, skipping", name)
            return

        # Substitute secrets in args (e.g. ["--token", "${GITHUB_PAT}"])
        resolved_args = [
            self._substitute_secrets(str(a)) for a in args
        ]

        server_params = StdioServerParameters(
            command=command,
            args=resolved_args,
            env=self._build_env(env),
        )

        logger.info("Connecting to MCP server '%s' (stdio): %s %s", name, command, " ".join(resolved_args))

        transport = await self._exit_stack.enter_async_context(
            stdio_client(server_params)
        )
        read, write = transport
        session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await session.initialize()

        self._sessions[name] = session
        await self._register_tools(name, session)

    async def _connect_http(self, name: str, config: dict):
        """Connect to an MCP server via HTTP (streamable HTTP) transport."""
        url = config.get("url")
        if not url:
            logger.warning("MCP server '%s' has no URL, skipping", name)
            return

        headers = config.get("headers", {})
        # Substitute secrets in headers and cast all values to str
        resolved_headers = {
            k: self._substitute_secrets(str(v))
            for k, v in headers.items()
        }

        logger.info("Connecting to MCP server '%s' (http): %s", name, url)

        try:
            from mcp.client.streamable_http import streamable_http_client

            transport = await self._exit_stack.enter_async_context(
                streamable_http_client(url, headers=resolved_headers)
            )
            read, write, _ = transport
            session = await self._exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await session.initialize()

            self._sessions[name] = session
            await self._register_tools(name, session)
        except ImportError:
            logger.warning("MCP HTTP transport not available — upgrade mcp package. Skipping '%s'", name)
        except Exception as e:
            raise  # re-raise so the caller logs the specific error

    async def _register_tools(self, name: str, session: ClientSession):
        """Discover tools from a connected session and register them."""
        from src import tools as local_tools
        local_names = set(local_tools.TOOL_REGISTRY.keys())

        response = await session.list_tools()
        for tool in response.tools:
            if tool.name in local_names:
                logger.warning(
                    "MCP tool '%s' from '%s' conflicts with local tool — local takes priority",
                    tool.name, name,
                )
                continue
            if tool.name in self._tools:
                prev_server = self._tools[tool.name][0]
                logger.warning(
                    "MCP tool '%s' from '%s' conflicts with '%s' — keeping first",
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
