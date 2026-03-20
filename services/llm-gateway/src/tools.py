"""Tool registry for Phase 6 — Tool Use & Function Calling.

Tools are functions the LLM can request during a conversation. The gateway
executes them and feeds results back. The model never runs tools itself —
it just asks for them via structured tool_calls in the response.

=== HOW TO ADD A NEW TOOL ===

Step 1: Write the function
    - Takes simple args (str, int, float, bool) and returns a str
    - Keep it focused — one tool, one job
    - Handle errors internally (return error messages, don't raise)

    def my_tool(query: str, limit: int = 5) -> str:
        '''One-line description of what it does.'''
        try:
            result = do_something(query, limit)
            return str(result)
        except Exception as e:
            return f"Error: {e}"

Step 2: Add to TOOL_REGISTRY
    - The key is the tool name (must match the schema name)
    - "fn" points to your function
    - "schema" is what the model sees — the description is critical because
      the model reads it to decide WHEN to call your tool

    "my_tool": {
        "fn": my_tool,
        "schema": {
            "type": "function",
            "function": {
                "name": "my_tool",
                "description": (
                    "When to use this tool and what it does. Be specific — "
                    "the model uses this to decide if the tool is relevant."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "What to search for",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results to return (default 5)",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
    },

Step 3: That's it — the gateway auto-discovers the tool.

=== TIPS ===

- The description is the most important part. The model reads it to decide
  when to call the tool. Be specific: "Use this when the user asks about X"
  works better than "Does X".

- Parameter descriptions matter too — they tell the model what to pass.

- Return strings, not dicts. The result goes back to the model as text in
  a role:"tool" message.

- Don't call external APIs that require secrets in the tool function itself.
  If you need an API key, read it from config/env at module level.

- Keep tools fast. The user is waiting while tools execute. If a tool is
  slow, consider caching or timeouts.

- Test your tool in isolation first:
      python -c "from src.tools import my_tool; print(my_tool('test'))"

=== SCHEMA REFERENCE ===

The schema follows Ollama's format (same as OpenAI function calling):
    {
        "type": "function",
        "function": {
            "name": "tool_name",
            "description": "What this tool does — be specific!",
            "parameters": {
                "type": "object",
                "properties": {
                    "arg_name": {
                        "type": "string|integer|number|boolean",
                        "description": "What this argument is for"
                    }
                },
                "required": ["arg_name"]
            }
        }
    }

Supported parameter types: string, integer, number, boolean, array, object.
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
