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

import ast
import logging
import math
from datetime import datetime, timezone

import httpx

from ai_lab_common.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


_MAX_EXPRESSION_LEN = 200
_MAX_EXPONENT = 1000

# AST node types allowed in calculator expressions — only arithmetic.
_SAFE_AST_NODES = (
    ast.Expression, ast.Module,
    ast.BinOp, ast.UnaryOp, ast.Call, ast.Name, ast.Constant, ast.Load,
    # Operators
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow,
    ast.USub, ast.UAdd,
)


def _validate_ast(node: ast.AST) -> str | None:
    """Walk the AST and reject anything that isn't simple arithmetic.

    Returns an error message if something unsafe is found, None if OK.
    Blocks list/dict/set literals, comprehensions, subscripts, starred
    expressions, and anything else that could cause resource exhaustion.
    """
    for child in ast.walk(node):
        if not isinstance(child, _SAFE_AST_NODES):
            return f"'{type(child).__name__}' is not allowed in calculator expressions"
        # Cap exponent size to prevent 10**10000000
        if isinstance(child, ast.BinOp) and isinstance(child.op, ast.Pow):
            if isinstance(child.right, ast.Constant) and isinstance(child.right.value, (int, float)):
                if abs(child.right.value) > _MAX_EXPONENT:
                    return f"Exponent too large (max {_MAX_EXPONENT})"
    return None


def calculator(expression: str) -> str:
    """Evaluate a math expression safely.

    Supports basic arithmetic, powers, sqrt, abs, round, and common math
    constants (pi, e). No imports, no exec, no eval of arbitrary code.
    Validates the AST to block resource exhaustion (large exponents,
    list/dict literals, comprehensions).
    """
    if len(expression) > _MAX_EXPRESSION_LEN:
        return f"Error: expression too long (max {_MAX_EXPRESSION_LEN} chars)"

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
        # Parse to AST and validate structure before eval
        tree = ast.parse(expression, mode="eval")
        error = _validate_ast(tree)
        if error:
            return f"Error: {error}"

        code = compile(tree, "<calculator>", "eval")
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


# User ID passed per-request via execute_tool (no global state).
# Stored in a thread-local so save_memory can access it from a threadpool.
import threading as _threading
_tool_context = _threading.local()


def save_memory(fact: str) -> str:
    """Save a fact about the user for future conversations.

    Use this when the user explicitly asks you to remember something,
    or when you learn an important preference or fact about them.
    """
    import asyncio
    from src import db

    user_id = getattr(_tool_context, "user_id", None)
    if not user_id:
        return "Error: no user context available"
    if not fact.strip():
        return "Error: empty fact"

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            future = asyncio.run_coroutine_threadsafe(
                db.add_user_memory(user_id, fact.strip()),
                loop,
            )
            future.result(timeout=5)
        else:
            asyncio.run(db.add_user_memory(user_id, fact.strip()))
        return f"Remembered: {fact.strip()}"
    except Exception as e:
        return f"Error saving memory: {e}"


_SEARXNG_URL = settings.SEARXNG_URL
_search_client = httpx.Client(timeout=15, follow_redirects=True)


def web_search(query: str, num_results: int = 5) -> str:
    """Search the web using SearXNG and return top results.

    Returns a formatted list of results with title, URL, and snippet.
    """
    try:
        resp = _search_client.get(
            f"{_SEARXNG_URL}/search",
            params={"q": query, "format": "json", "categories": "general"},
            headers={
                "X-Forwarded-For": "127.0.0.1",
                "X-Real-IP": "127.0.0.1",
            },
        )
        if resp.status_code != 200:
            logger.warning("SearXNG returned %d: %s", resp.status_code, resp.text[:200])
        resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")
        if "json" not in content_type:
            logger.warning("SearXNG returned %s instead of JSON", content_type)
            return "Error: search returned HTML instead of JSON (check SearXNG formats config)"

        data = resp.json()
        results = data.get("results", [])[:num_results]
        if not results:
            return f"No results found for: {query}"

        lines = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "No title")
            url = r.get("url", "")
            snippet = r.get("content", "")
            lines.append(f"{i}. {title}\n   {url}\n   {snippet}")
        return "\n\n".join(lines)
    except httpx.ConnectError:
        return "Error: search service unavailable (SearXNG not running)"
    except Exception as e:
        logger.error("web_search failed: %s", e)
        return f"Error searching: {e}"


# Conversion factors: from_unit → {to_unit: factor}
# Temperature is handled separately (non-linear).
_CONVERSIONS = {
    # Length
    "m": {"cm": 100, "mm": 1000, "km": 0.001, "in": 39.3701, "ft": 3.28084, "mi": 0.000621371},
    "cm": {"m": 0.01, "mm": 10, "in": 0.393701, "ft": 0.0328084},
    "mm": {"m": 0.001, "cm": 0.1, "in": 0.0393701},
    "km": {"m": 1000, "mi": 0.621371, "ft": 3280.84},
    "mi": {"km": 1.60934, "m": 1609.34, "ft": 5280},
    "ft": {"m": 0.3048, "cm": 30.48, "in": 12, "mi": 0.000189394},
    "in": {"cm": 2.54, "mm": 25.4, "ft": 0.0833333, "m": 0.0254},
    # Weight
    "kg": {"g": 1000, "lb": 2.20462, "oz": 35.274},
    "g": {"kg": 0.001, "lb": 0.00220462, "oz": 0.035274},
    "lb": {"kg": 0.453592, "g": 453.592, "oz": 16},
    "oz": {"g": 28.3495, "lb": 0.0625, "kg": 0.0283495},
    # Volume
    "l": {"ml": 1000, "gal": 0.264172, "qt": 1.05669},
    "ml": {"l": 0.001, "oz_fl": 0.033814},
    "gal": {"l": 3.78541, "qt": 4},
    "qt": {"l": 0.946353, "gal": 0.25},
    "oz_fl": {"ml": 29.5735, "l": 0.0295735},
}


def unit_convert(value: float, from_unit: str, to_unit: str) -> str:
    """Convert a value between units.

    Supports length (m, cm, mm, km, mi, ft, in), weight (kg, g, lb, oz),
    volume (l, ml, gal), and temperature (celsius, fahrenheit, kelvin).
    """
    f = from_unit.lower().strip()
    t = to_unit.lower().strip()

    if f == t:
        return f"{value} {from_unit} = {value} {to_unit}"

    # Temperature (non-linear conversions)
    temp_units = {"celsius", "fahrenheit", "kelvin", "c", "f", "k"}
    if f in temp_units and t in temp_units:
        # Normalize aliases
        f = {"c": "celsius", "f": "fahrenheit", "k": "kelvin"}.get(f, f)
        t = {"c": "celsius", "f": "fahrenheit", "k": "kelvin"}.get(t, t)
        if f == "celsius" and t == "fahrenheit":
            r = value * 9 / 5 + 32
        elif f == "celsius" and t == "kelvin":
            r = value + 273.15
        elif f == "fahrenheit" and t == "celsius":
            r = (value - 32) * 5 / 9
        elif f == "fahrenheit" and t == "kelvin":
            r = (value - 32) * 5 / 9 + 273.15
        elif f == "kelvin" and t == "celsius":
            r = value - 273.15
        elif f == "kelvin" and t == "fahrenheit":
            r = (value - 273.15) * 9 / 5 + 32
        else:
            return f"Error: unsupported temperature conversion {from_unit} → {to_unit}"
        return f"{value} {from_unit} = {round(r, 2)} {to_unit}"

    # Linear conversions
    if f in _CONVERSIONS and t in _CONVERSIONS.get(f, {}):
        r = value * _CONVERSIONS[f][t]
        return f"{value} {from_unit} = {round(r, 4)} {to_unit}"

    return f"Error: unsupported conversion {from_unit} → {to_unit}"


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
    "unit_convert": {
        "fn": unit_convert,
        "schema": {
            "type": "function",
            "function": {
                "name": "unit_convert",
                "description": (
                    "Convert a value between units. Supports length (m, cm, mm, km, mi, ft, in), "
                    "weight (kg, g, lb, oz), volume (l, ml, gal), and temperature "
                    "(celsius, fahrenheit, kelvin). Use this when the user asks to convert units."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "value": {
                            "type": "number",
                            "description": "The numeric value to convert",
                        },
                        "from_unit": {
                            "type": "string",
                            "description": "The source unit (e.g. 'km', 'lb', 'celsius')",
                        },
                        "to_unit": {
                            "type": "string",
                            "description": "The target unit (e.g. 'mi', 'kg', 'fahrenheit')",
                        },
                    },
                    "required": ["value", "from_unit", "to_unit"],
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
                    "Search the web for current information. Use this when the user asks about "
                    "recent events, news, weather, prices, people, places, or anything that "
                    "requires up-to-date information beyond your training data. Also use this "
                    "when you're not sure about a fact and want to verify it."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query (e.g. 'weather in Amsterdam today')",
                        },
                        "num_results": {
                            "type": "integer",
                            "description": "Number of results to return (default 5, max 10)",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
    },
    "save_memory": {
        "fn": save_memory,
        "schema": {
            "type": "function",
            "function": {
                "name": "save_memory",
                "description": (
                    "Save a fact about the user for future conversations. "
                    "Use this when the user says 'remember that...' or when you learn "
                    "an important preference, background detail, or decision. "
                    "The fact will be available in all future conversations."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "fact": {
                            "type": "string",
                            "description": "The fact to remember (e.g. 'User prefers concise responses')",
                        },
                    },
                    "required": ["fact"],
                },
            },
        },
    },
}


def get_tool_schemas() -> list[dict]:
    """Return the list of tool schemas for the Ollama API."""
    return [entry["schema"] for entry in TOOL_REGISTRY.values()]


def execute_tool(name: str, arguments: dict, user_id: str | None = None) -> str:
    """Execute a tool by name with the given arguments.

    user_id is set on thread-local so save_memory can access it safely
    without global mutable state (no race conditions under concurrent requests).
    """
    # Set user context on thread-local for this execution
    _tool_context.user_id = user_id

    entry = TOOL_REGISTRY.get(name)
    if not entry:
        logger.warning("Unknown tool requested: %s", name)
        return f"Error: unknown tool '{name}'"

    fn = entry["fn"]
    try:
        result = str(fn(**arguments))
        logger.info("Tool %s(%s) → %s", name, arguments, result[:100])
        return result
    except Exception as e:
        logger.error("Tool %s failed: %s", name, e)
        return f"Error running {name}: {e}"
