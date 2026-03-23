-- Secrets store for MCP server credentials and API keys.
-- Admin-only. Values are stored as plain text (DB access = full access on this LAN app).
-- Referenced in MCP configs via ${SECRET_NAME} syntax.
CREATE TABLE IF NOT EXISTS secrets (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
