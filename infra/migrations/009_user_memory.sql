-- Per-user persistent memory for cross-conversation context.
-- The model can store and retrieve facts about each user
-- (preferences, background, past decisions) to maintain
-- continuity across conversations.
CREATE TABLE IF NOT EXISTS user_memory (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content    TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_memory_user_id ON user_memory(user_id);
