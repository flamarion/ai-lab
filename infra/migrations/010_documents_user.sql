-- Per-user document scoping: ownership + visibility
-- Existing documents (NULL user_id) are treated as shared.

ALTER TABLE documents ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_private BOOLEAN NOT NULL DEFAULT false;
