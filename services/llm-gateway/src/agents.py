"""Agent registry — DB-configurable specialized agents with keyword routing.

Each agent has a system prompt, optional model override, allowed tools,
and routing keywords.  The registry loads agents from Postgres and matches
incoming messages to the most relevant agent via keyword scoring.

Reliability patterns:
- Retry with fallback: agent failures retry once, then fall back to default
- Timeout: configurable per-agent timeout (default 120s)
- Error isolation: one agent's failure doesn't crash the request
- Graceful degradation: if registry is unavailable, use default flow
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

from src import db

logger = logging.getLogger(__name__)

# Reliability defaults
AGENT_TIMEOUT_SECONDS = 120  # per-agent subtask timeout
MAX_RETRIES = 1  # retry once on failure before falling back


@dataclass
class AgentConfig:
    """In-memory representation of a configured agent."""
    id: str
    name: str
    description: str = ""
    system_prompt: str = ""
    model: str | None = None
    tools: list[str] = field(default_factory=list)
    routing_keywords: list[str] = field(default_factory=list)
    enabled: bool = True

    # Pre-compiled regex for keyword matching (built on load)
    _pattern: re.Pattern | None = field(default=None, repr=False)

    def compile_pattern(self) -> None:
        """Build a regex from routing_keywords for fast matching."""
        if self.routing_keywords:
            self._pattern = re.compile(
                r"\b(" + "|".join(re.escape(kw) for kw in self.routing_keywords) + r")\b",
                re.IGNORECASE,
            )
        else:
            self._pattern = None

    def score(self, message: str) -> int:
        """Count how many distinct routing keywords match the message."""
        if not self._pattern:
            return 0
        return len(set(self._pattern.findall(message.lower())))


# Default agents seeded on first startup when the table is empty.
_DEFAULT_AGENTS = [
    {
        "name": "Researcher",
        "description": "Gathers information using web search and URL fetching. Good for current events, facts, comparisons, and data lookup.",
        "system_prompt": (
            "You are a research specialist. Your job is to find accurate, "
            "up-to-date information using your tools.\n\n"
            "Guidelines:\n"
            "- Use web_search for current events, news, prices, weather, and facts\n"
            "- Fetch URLs when you need the full content of a specific page\n"
            "- Cross-reference multiple sources when possible\n"
            "- Always cite your sources\n"
            "- If you can't find reliable information, say so clearly\n"
            "- Summarize findings concisely — don't dump raw search results"
        ),
        "tools": ["web_search"],
        "routing_keywords": [
            "search", "find", "look up", "research", "news", "weather",
            "price", "cost", "current", "latest", "today", "recent",
            "compare", "statistics", "data", "how many", "how much",
            "who is", "what is", "when did", "where is",
        ],
    },
    {
        "name": "Coder",
        "description": "Writes, explains, and debugs code. Handles programming questions, algorithms, and technical problem-solving.",
        "system_prompt": (
            "You are a coding specialist. Your job is to write clean, "
            "correct, and well-explained code.\n\n"
            "Guidelines:\n"
            "- Write code that is readable and follows best practices\n"
            "- Explain your approach before writing code\n"
            "- Use the calculator tool for complex math\n"
            "- Include comments for non-obvious logic\n"
            "- If the user's code has bugs, explain what's wrong and why\n"
            "- Suggest improvements but respect the user's style"
        ),
        "tools": ["calculator", "current_time"],
        "routing_keywords": [
            "code", "function", "class", "debug", "error", "bug",
            "python", "javascript", "typescript", "java", "rust", "golang",
            "implement", "refactor", "optimize", "algorithm", "regex",
            "api", "endpoint", "database", "sql", "html", "css",
            "docker", "git", "deploy", "test", "compile",
        ],
    },
]


class AgentRegistry:
    """Manages agent configs loaded from the database."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentConfig] = {}
        self._loaded = False

    async def load(self) -> None:
        """Load agents from the database.  Seeds defaults if the table is empty."""
        if not db.is_available():
            logger.warning("Database unavailable — agent registry empty")
            return

        try:
            rows = await db.list_agents()

            # Seed defaults only on first startup, not on subsequent reloads
            # (so admins can delete all agents without them reappearing).
            if not rows and not self._loaded:
                logger.info("No agents in DB — seeding defaults")
                await self._seed_defaults()
                rows = await db.list_agents()

            self._agents.clear()
            for row in rows:
                agent = AgentConfig(
                    id=row["id"],
                    name=row["name"],
                    description=row.get("description", ""),
                    system_prompt=row.get("system_prompt", ""),
                    model=row.get("model"),
                    tools=row.get("tools", []),
                    routing_keywords=row.get("routing_keywords", []),
                    enabled=row.get("enabled", True),
                )
                agent.compile_pattern()
                self._agents[agent.name] = agent

            self._loaded = True
            logger.info(
                "Loaded %d agent(s): %s",
                len(self._agents),
                ", ".join(self._agents.keys()),
            )
        except Exception as e:
            logger.warning("Failed to load agents: %s", e)

    async def _seed_defaults(self) -> None:
        """Insert the default Researcher and Coder agents."""
        for agent_def in _DEFAULT_AGENTS:
            try:
                await db.upsert_agent(agent_def)
            except Exception as e:
                logger.warning("Failed to seed agent %s: %s", agent_def["name"], e)

    def list_agents(self) -> list[AgentConfig]:
        """Return all agents (enabled and disabled)."""
        return list(self._agents.values())

    def get_agent(self, name: str) -> AgentConfig | None:
        """Look up an agent by name."""
        return self._agents.get(name)

    def route(self, message: str) -> AgentConfig | None:
        """Pick the best agent for a message based on keyword scoring.

        Returns the highest-scoring enabled agent, or None if no agent
        matches (falls back to default behavior).
        """
        best: AgentConfig | None = None
        best_score = 0

        for agent in self._agents.values():
            if not agent.enabled:
                continue
            score = agent.score(message)
            if score > best_score:
                best = agent
                best_score = score

        if best and best_score > 0:
            logger.info("Routed to agent '%s' (score=%d)", best.name, best_score)
            return best

        return None


    def route_multi(self, message: str) -> list[tuple[AgentConfig, int]]:
        """Score all enabled agents. Returns [(agent, score)] sorted by score desc.

        Useful for the orchestrator to decide if multiple agents should
        collaborate on a task.
        """
        scored = []
        for agent in self._agents.values():
            if not agent.enabled:
                continue
            score = agent.score(message)
            if score > 0:
                scored.append((agent, score))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored


# Prompt template for task decomposition
DECOMPOSE_PROMPT = (
    "You are a task orchestrator. Given a user request and a list of available "
    "specialized agents, decide whether the task needs multiple agents or just one.\n\n"
    "Available agents:\n{agent_list}\n\n"
    "Rules:\n"
    "- If the task clearly maps to a single agent, output: SINGLE <agent_name>\n"
    "- If the task needs multiple agents, output a numbered plan where each step "
    "is assigned to an agent:\n"
    "  1. [AgentName] description of subtask\n"
    "  2. [AgentName] description of subtask\n"
    "- Keep it to 2-4 steps maximum\n"
    "- Output ONLY the routing decision, nothing else"
)

SYNTHESIZE_PROMPT = (
    "You are synthesizing results from multiple specialized agents into a "
    "coherent final answer for the user.\n\n"
    "The user asked: {question}\n\n"
    "Here are the results from each agent:\n{results}\n\n"
    "Combine these into a clear, well-organized response. "
    "Credit the sources where appropriate."
)


@dataclass
class SubTask:
    """A subtask assigned to a specific agent."""
    agent_name: str
    description: str
    result: str = ""


async def decompose_task(
    message: str,
    agents: list[AgentConfig],
    llm_client,
    model: str,
) -> list[SubTask] | None:
    """Use the LLM to decide if a task needs multiple agents.

    Returns a list of SubTasks if decomposition is needed,
    or None if a single agent suffices (caller should use normal routing).
    """
    agent_list = "\n".join(
        f"- {a.name}: {a.description}" for a in agents
    )
    prompt = DECOMPOSE_PROMPT.format(agent_list=agent_list)

    try:
        response = await llm_client.chat(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": message},
            ],
            options={"temperature": 0.2, "num_predict": 200},
        )

        response = response.strip()

        # Single agent — no decomposition needed
        if response.upper().startswith("SINGLE"):
            return None

        # Parse numbered plan: "1. [AgentName] description"
        subtasks = []
        for line in response.splitlines():
            line = line.strip()
            if not line or not line[0].isdigit():
                continue
            # Remove leading number and punctuation
            line = re.sub(r"^\d+[\.\)]\s*", "", line)
            # Extract [AgentName]
            match = re.match(r"\[([^\]]+)\]\s*(.*)", line)
            if match:
                agent_name = match.group(1).strip()
                description = match.group(2).strip()
                subtasks.append(SubTask(agent_name=agent_name, description=description))

        if len(subtasks) >= 2:
            logger.info("Decomposed into %d subtasks: %s", len(subtasks),
                        [(s.agent_name, s.description[:50]) for s in subtasks])
            return subtasks

    except Exception as e:
        logger.warning("Task decomposition failed: %s", e)

    return None


async def synthesize_results(
    question: str,
    subtasks: list[SubTask],
    llm_client,
    model: str,
) -> str:
    """Combine results from multiple agent subtasks into a final answer."""
    results_text = "\n\n".join(
        f"### {st.agent_name}: {st.description}\n{st.result}"
        for st in subtasks if st.result
    )
    prompt = SYNTHESIZE_PROMPT.format(question=question, results=results_text)

    try:
        return await llm_client.chat(
            model=model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": "Please synthesize the results above."},
            ],
            options={"temperature": 0.3, "num_predict": 1000},
        )
    except Exception as e:
        logger.warning("Synthesis failed: %s — returning raw results", e)
        return results_text


async def execute_subtask_reliable(
    subtask: SubTask,
    agent: AgentConfig | None,
    llm_client,
    model: str,
    options: dict | None = None,
    user_id: str | None = None,
    timeout: float = AGENT_TIMEOUT_SECONDS,
) -> tuple[str, list[dict]]:
    """Execute a subtask with retry, timeout, and error isolation.

    Returns (result_text, tools_used).  On failure, returns an error
    message instead of raising — the orchestrator can still continue
    with partial results.
    """
    sub_model = (agent.model if agent and agent.model else model)
    sub_messages = []
    if agent and agent.system_prompt:
        sub_messages.append({"role": "system", "content": f"## Agent: {agent.name}\n{agent.system_prompt}"})
    sub_messages.append({"role": "user", "content": subtask.description})

    last_error = None
    for attempt in range(1 + MAX_RETRIES):
        try:
            start = time.monotonic()
            result, tools_used = await asyncio.wait_for(
                llm_client.chat_with_tools(
                    model=sub_model, messages=sub_messages, options=options,
                    user_id=user_id,
                    allowed_tools=agent.tools if agent and agent.tools else None,
                ),
                timeout=timeout,
            )
            elapsed = time.monotonic() - start
            logger.info(
                "Subtask '%s' completed by %s in %.1fs (attempt %d)",
                subtask.description[:50],
                agent.name if agent else "default",
                elapsed,
                attempt + 1,
            )
            return result, tools_used

        except asyncio.TimeoutError:
            last_error = f"Timed out after {timeout}s"
            logger.warning(
                "Subtask '%s' timed out (attempt %d/%d)",
                subtask.description[:50], attempt + 1, 1 + MAX_RETRIES,
            )
        except Exception as e:
            last_error = str(e)
            logger.warning(
                "Subtask '%s' failed (attempt %d/%d): %s",
                subtask.description[:50], attempt + 1, 1 + MAX_RETRIES, e,
            )

    # All retries exhausted — return error as result (don't crash the request)
    error_msg = f"[Agent {agent.name if agent else 'default'} failed: {last_error}]"
    return error_msg, []


# Module-level singleton
registry = AgentRegistry()
