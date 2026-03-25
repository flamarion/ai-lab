"""OAuth 2.0 support for MCP servers that require browser-based authentication.

Some MCP servers (like Granola) use OAuth 2.0 instead of API keys. The flow:
1. Admin clicks "Connect" in the UI for an OAuth-enabled MCP server
2. Gateway generates an authorization URL and returns it
3. Admin's browser opens the URL — they authenticate with the provider
4. Provider redirects back to our callback URL with an auth code
5. Gateway exchanges the code for a bearer token
6. Token is stored as a secret and used in MCP HTTP headers

MCP server config format for OAuth:
{
    "transport": "http",
    "url": "https://mcp.example.com/mcp",
    "oauth": {
        "authorize_url": "https://provider.com/oauth/authorize",
        "token_url": "https://provider.com/oauth/token",
        "client_id": "your-client-id",
        "scope": "openid profile"
    }
}

The bearer token is stored as a secret named "oauth_<server_name>"
and referenced in headers via ${oauth_<server_name>}.
"""

import base64
import hashlib
import html
import logging
import os
import secrets
import time
from urllib.parse import urlencode

import httpx

from src import db

logger = logging.getLogger(__name__)

# In-flight OAuth states (state → flow data). Expires after 10 minutes.
_pending_flows: dict[str, dict] = {}
_FLOW_EXPIRY_SECONDS = 600


def _cleanup_expired():
    """Remove expired pending flows."""
    now = time.time()
    expired = [k for k, v in _pending_flows.items() if now - v.get("created_at", 0) > _FLOW_EXPIRY_SECONDS]
    for k in expired:
        del _pending_flows[k]


def get_callback_url() -> str:
    """Return the OAuth callback URL for this gateway."""
    host = os.getenv("OAUTH_CALLBACK_HOST", "http://localhost/api")
    return f"{host}/oauth/callback"


def validate_oauth_config(oauth_config: dict) -> str | None:
    """Validate required OAuth fields. Returns error message or None."""
    if not oauth_config.get("authorize_url"):
        return "oauth.authorize_url is required"
    if not oauth_config.get("token_url"):
        return "oauth.token_url is required"
    return None


def start_flow(server_name: str, oauth_config: dict) -> str:
    """Generate an OAuth authorization URL and return it."""
    _cleanup_expired()

    state = secrets.token_urlsafe(32)
    code_verifier = secrets.token_urlsafe(64)
    # PKCE S256: base64url(sha256(verifier)) without padding
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )

    _pending_flows[state] = {
        "server_name": server_name,
        "code_verifier": code_verifier,
        "token_url": oauth_config["token_url"],
        "client_id": oauth_config.get("client_id", ""),
        "created_at": time.time(),
    }

    params = {
        "response_type": "code",
        "client_id": oauth_config.get("client_id", ""),
        "redirect_uri": get_callback_url(),
        "state": state,
        "scope": oauth_config.get("scope", "openid"),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }

    authorize_url = oauth_config["authorize_url"]
    return f"{authorize_url}?{urlencode(params)}"


async def handle_callback(code: str, state: str) -> dict:
    """Exchange the authorization code for a token and store it.

    Returns {"server_name": str, "success": bool, "error": str|None}.
    """
    _cleanup_expired()

    flow = _pending_flows.pop(state, None)
    if not flow:
        return {"server_name": "unknown", "success": False, "error": "Invalid or expired OAuth state"}

    server_name = flow["server_name"]

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                flow["token_url"],
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": get_callback_url(),
                    "client_id": flow["client_id"],
                    "code_verifier": flow["code_verifier"],
                },
                timeout=15.0,
            )

        if resp.status_code != 200:
            return {"server_name": server_name, "success": False, "error": f"Token exchange failed (HTTP {resp.status_code})"}

        token_data = resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            return {"server_name": server_name, "success": False, "error": "No access_token in response"}

        # Store the token as a secret — fail if DB unavailable
        if not db.is_available():
            return {"server_name": server_name, "success": False, "error": "Database unavailable — cannot store token"}

        secret_key = f"oauth_{server_name}"
        await db.set_secret(secret_key, access_token)
        logger.info("Stored OAuth token for MCP server '%s' as secret '%s'", server_name, secret_key)

        return {"server_name": server_name, "success": True, "error": None}

    except Exception as e:
        logger.error("OAuth token exchange failed for '%s': %s", server_name, e)
        # Return generic error — don't leak exception details to the browser
        return {"server_name": server_name, "success": False, "error": "Token exchange failed — check gateway logs"}


def render_callback_page(result: dict) -> str:
    """Render a safe HTML page for the OAuth callback result."""
    name = html.escape(result.get("server_name", "unknown"))
    if result["success"]:
        return (
            f"<html><body><h2>Connected to {name}</h2>"
            "<p>You can close this window.</p>"
            "<script>setTimeout(() => window.close(), 2000)</script></body></html>"
        )
    else:
        error = html.escape(result.get("error", "Unknown error"))
        return (
            f"<html><body><h2>Connection failed</h2>"
            f"<p>{error}</p></body></html>"
        )
