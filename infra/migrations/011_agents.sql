-- Phase 8: Specialized agents — DB-configurable agent registry
-- Each agent has a name, system prompt, optional model override,
-- allowed tools, and routing keywords for auto-selection.

CREATE TABLE IF NOT EXISTS agents (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name             TEXT NOT NULL UNIQUE,
    description      TEXT NOT NULL DEFAULT '',
    system_prompt    TEXT NOT NULL DEFAULT '',
    model            TEXT,
    tools            TEXT[] NOT NULL DEFAULT '{}',
    routing_keywords TEXT[] NOT NULL DEFAULT '{}',
    enabled          BOOLEAN NOT NULL DEFAULT true,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
