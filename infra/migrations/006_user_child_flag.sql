-- Flag users as children (for future guardrails)
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_child BOOLEAN NOT NULL DEFAULT false;
