-- Add attachments column to messages for file metadata.
-- Stores [{name, type, size}] for display — actual content is in the message text.
ALTER TABLE messages ADD COLUMN IF NOT EXISTS attachments jsonb;
