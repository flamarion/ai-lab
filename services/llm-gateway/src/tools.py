"""Tool registry for Phase 6 — Tool Use & Function Calling.

Tools are functions the LLM can request during a conversation. The gateway
executes them and feeds results back. The model never runs tools itself —
it just asks for them via structured tool_calls in the response.

Adding a new tool:
    1. Write a function that takes simple args and returns a string
    2. Add it to TOOL_REGISTRY with an Ollama-compatible schema
    3. That's it — the gateway auto-discovers it

The schema follows Ollama's format (same as OpenAI function calling):
    {
        "type": "function",
        "function": {
            "name": "tool_name",
            "description": "What this tool does",
            "parameters": {
                "type": "object",
                "properties": { ... },
                "required": [...]
            }
        }
    }
"""

import logging
import math
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def calculator(expression: str) -> str:
    """Evaluate a math expression safely.

    Supports basic arithmetic, powers, sqrt, abs, round, and common math
    constants (pi, e). No imports, no exec, no eval of arbitrary code.
    """
    allowed_names = {
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "sqrt": math.sqrt,
        "pow": pow,
        "pi": math.pi,
        "e": math.e,
        "log": math.log,
        "log10": math.log10,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
    }
    try:
        # Compile to AST first — rejects anything that isn't an expression
        code = compile(expression, "<calculator>", "eval")
        # Check that only allowed names are referenced
        for name in code.co_names:
            if name not in allowed_names:
                return f"Error: '{name}' is not allowed in calculator expressions"
        result = eval(code, {"__builtins__": {}}, allowed_names)
        return str(result)
    except Exception as e:
        return f"Error: {e}"


def current_time() -> str:
    """Return the current date and time in UTC and a human-readable format."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d %H:%M:%S UTC (%A)")


def web_search(query: str) -> str:
    """Search the web using DuckDuckGo and return top results.

    Uses the DuckDuckGo HTML endpoint (no API key needed). Returns titles
    and snippets for the top results, or an error message on failure.
    """
    import httpx

    try:
        resp = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (AI Lab Gateway)"},
            timeout=10.0,
            follow_redirects=True,
        )
        resp.raise_for_status()

        # Parse results from the HTML (DuckDuckGo's HTML endpoint)
        # Each result is in a div with class "result"
        import re

        results = []
        # Extract result titles and snippets
        for match in re.finditer(
            r'class="result__a"[^>]*>(.+?)</a>.*?'
            r'class="result__snippet"[^>]*>(.+?)</span>',
            resp.text,
            re.DOTALL,
        ):
            title = re.sub(r"<[^>]+>", "", match.group(1)).strip()
            snippet = re.sub(r"<[^>]+>", "", match.group(2)).strip()
            if title and snippet:
                results.append(f"- {title}: {snippet}")
            if len(results) >= 5:
                break

        if results:
            return "\n".join(results)
        return "No results found."
    except Exception as e:
        return f"Search failed: {e}"


# ---------------------------------------------------------------------------
# Tool registry — maps tool names to (function, schema)
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, dict] = {
    "calculator": {
        "fn": calculator,
        "schema": {
            "type": "function",
            "function": {
                "name": "calculator",
                "description": (
                    "Evaluate a mathematical expression. Use this for any arithmetic, "
                    "unit conversions, or calculations instead of doing math yourself."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {
                            "type": "string",
                            "description": "The math expression to evaluate, e.g. '2**10' or 'sqrt(144)'",
                        }
                    },
                    "required": ["expression"],
                },
            },
        },
    },
    "current_time": {
        "fn": current_time,
        "schema": {
            "type": "function",
            "function": {
                "name": "current_time",
                "description": (
                    "Get the current date and time. Use this when the user asks "
                    "about the current time, date, or day of the week."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
            },
        },
    },
    "web_search": {
        "fn": web_search,
        "schema": {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": (
                    "Search the web for current information. Use this when the user asks "
                    "about recent events, news, or anything that requires up-to-date data."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query",
                        }
                    },
                    "required": ["query"],
                },
            },
        },
    },
}


def get_tool_schemas() -> list[dict]:
    """Return the list of tool schemas for the Ollama API."""
    return [entry["schema"] for entry in TOOL_REGISTRY.values()]


def execute_tool(name: str, arguments: dict) -> str:
    """Execute a tool by name with the given arguments.

    Returns the tool result as a string, or an error message if the tool
    doesn't exist or fails.
    """
    entry = TOOL_REGISTRY.get(name)
    if not entry:
        logger.warning("Unknown tool requested: %s", name)
        return f"Error: unknown tool '{name}'"

    fn = entry["fn"]
    try:
        result = fn(**arguments)
        logger.info("Tool %s(%s) → %s", name, arguments, result[:100])
        return result
    except Exception as e:
        logger.error("Tool %s failed: %s", name, e)
        return f"Error running {name}: {e}"
