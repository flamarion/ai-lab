"""Context manager for conversation memory and token budgeting.

Handles two key problems:
1. Conversation summarization — compress old messages when approaching
   the context window limit, so the model doesn't lose early context.
2. User memory injection — persist key facts about users across
   conversations and inject them into the system prompt.

Token estimation uses a simple heuristic (chars / 4) since we don't
have access to the actual tokenizer. This is accurate enough for
context budgeting — we're estimating to decide when to summarize,
not doing exact token counting.
"""

import logging

from src import db

logger = logging.getLogger(__name__)

# Conservative token budget — leave room for the model's response
# and system prompt overhead. Ollama default is 16384.
DEFAULT_CONTEXT_LIMIT = 14000  # tokens (out of 16k)
SUMMARY_TRIGGER_RATIO = 0.7  # summarize when conversation uses 70% of budget
MIN_MESSAGES_TO_SUMMARIZE = 6  # don't summarize very short conversations

# System prompt for the summarizer
_SUMMARIZE_PROMPT = (
    "Summarize this conversation so far in 2-3 concise paragraphs. "
    "Preserve: the user's original request/intent, key decisions made, "
    "important context (names, numbers, preferences mentioned), and "
    "the current state of the discussion. Be factual and specific — "
    "this summary will replace the conversation history."
)

# System prompt for memory extraction
_MEMORY_EXTRACT_PROMPT = (
    "Based on this conversation, extract any new facts about the user "
    "that should be remembered for future conversations. Focus on: "
    "preferences, background, communication style, recurring topics, "
    "or explicit requests to remember something. "
    "Return ONLY the facts as a bulleted list, one per line. "
    "If there's nothing new to remember, reply with just: NONE"
)


def estimate_tokens(text: str) -> int:
    """Estimate token count from text. ~4 chars per token for English."""
    return len(text) // 4


def estimate_messages_tokens(messages: list[dict]) -> int:
    """Estimate total tokens in a message list."""
    return sum(estimate_tokens(m.get("content", "")) + 4 for m in messages)  # +4 per message overhead


async def build_system_prompt(
    user_id: str | None,
    user_system_prompt: str | None,
    rag_context: str | None,
) -> str | None:
    """Build the system prompt with user memory + custom prompt + RAG context.

    Memory is injected first so the model always has user context,
    then the user's custom system prompt, then RAG context.
    """
    parts = []

    # 1. User memory (cross-conversation persistence)
    if user_id and db.is_available():
        try:
            memory_text = await db.get_user_memory_text(user_id)
            if memory_text.strip():
                parts.append(
                    f"## What you know about this user\n{memory_text}\n\n"
                    "Use this context to personalize your responses. "
                    "If the user asks you to remember something, confirm it."
                )
        except Exception as e:
            logger.debug("Could not load user memory: %s", e)

    # 2. User's custom system prompt
    if user_system_prompt and user_system_prompt.strip():
        parts.append(user_system_prompt.strip())

    # 3. RAG context (if any)
    if rag_context:
        parts.append(rag_context)

    return "\n\n".join(parts) if parts else None


def should_summarize(messages: list[dict], context_limit: int = DEFAULT_CONTEXT_LIMIT) -> bool:
    """Check if the conversation is long enough to need summarization."""
    if len(messages) < MIN_MESSAGES_TO_SUMMARIZE:
        return False
    tokens = estimate_messages_tokens(messages)
    return tokens > context_limit * SUMMARY_TRIGGER_RATIO


async def summarize_conversation(
    messages: list[dict],
    client,  # OllamaClient
    model: str,
) -> list[dict]:
    """Compress a long conversation into a summary + recent messages.

    Keeps the last 4 messages intact (the recent context the user cares about)
    and summarizes everything before that into a single system message.
    Returns a new message list: [summary_system_msg, ...recent_messages].
    """
    if len(messages) < MIN_MESSAGES_TO_SUMMARIZE:
        return messages

    # Split: older messages to summarize, recent to keep
    keep_recent = 4
    to_summarize = messages[:-keep_recent]
    recent = messages[-keep_recent:]

    # Build the text to summarize
    summary_input = []
    for m in to_summarize:
        role = m.get("role", "unknown")
        content = m.get("content", "")
        if role != "system":  # don't include system prompts in the summary
            summary_input.append(f"{role}: {content}")

    if not summary_input:
        return messages

    summary_text = "\n\n".join(summary_input)

    try:
        summary = await client.chat(
            model=model,
            messages=[
                {"role": "system", "content": _SUMMARIZE_PROMPT},
                {"role": "user", "content": summary_text},
            ],
            options={"temperature": 0.3, "num_predict": 500},
        )

        logger.info(
            "Summarized %d messages (%d tokens) → %d tokens",
            len(to_summarize),
            estimate_tokens(summary_text),
            estimate_tokens(summary),
        )

        # Return: summary as a system message + recent messages
        return [
            {"role": "system", "content": f"## Conversation summary (earlier messages)\n{summary}"},
            *recent,
        ]
    except Exception as e:
        logger.warning("Summarization failed: %s — using full history", e)
        return messages


async def extract_memories(
    messages: list[dict],
    client,  # OllamaClient
    model: str,
    user_id: str,
) -> list[str]:
    """Extract new facts about the user from the conversation and save them.

    Called after a conversation ends or periodically. Returns the list
    of new memories that were saved.
    """
    if not db.is_available() or len(messages) < 4:
        return []

    # Build conversation text for the extractor
    conv_text = "\n".join(
        f"{m['role']}: {m['content']}"
        for m in messages
        if m.get("role") in ("user", "assistant")
    )

    try:
        response = await client.chat(
            model=model,
            messages=[
                {"role": "system", "content": _MEMORY_EXTRACT_PROMPT},
                {"role": "user", "content": conv_text},
            ],
            options={"temperature": 0.1, "num_predict": 300},
        )

        if "NONE" in response.upper().strip():
            return []

        # Parse bullet points
        new_memories = []
        for line in response.strip().splitlines():
            line = line.strip().lstrip("-•*").strip()
            if line and len(line) > 10:  # skip very short/empty lines
                await db.add_user_memory(user_id, line)
                new_memories.append(line)
                logger.info("Saved memory for user %s: %s", user_id[:8], line[:60])

        return new_memories
    except Exception as e:
        logger.warning("Memory extraction failed: %s", e)
        return []
