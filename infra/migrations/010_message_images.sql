-- Add images column to messages table for vision support.
-- Stores base64-encoded image strings attached to a message.
ALTER TABLE messages ADD COLUMN IF NOT EXISTS images text[];
