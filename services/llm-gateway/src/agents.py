"""Agent registry — DB-configurable specialized agents with keyword routing.

Each agent has a system prompt, optional model override, allowed tools,
and routing keywords.  The registry loads agents from Postgres and matches
incoming messages to the most relevant agent via keyword scoring.
"""

import logging
import re
from dataclasses import dataclass, field

from src import db

logger = logging.getLogger(__name__)


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

            # Seed defaults on first run
            if not rows:
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


# Module-level singleton
registry = AgentRegistry()
