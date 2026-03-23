-- MCP server configuration persistence.
-- Single-row table storing the full mcpServers JSON config.
-- Survives container restarts (unlike the baked-in mcp_servers.json).
CREATE TABLE IF NOT EXISTS mcp_config (
    id         INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    config     JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO mcp_config (config) VALUES ('{}') ON CONFLICT DO NOTHING;
