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

import hashlib
import logging
import os
import secrets
from urllib.parse import urlencode

import httpx

from src import db

logger = logging.getLogger(__name__)

# In-flight OAuth states (state → {server_name, redirect_uri, code_verifier})
_pending_flows: dict[str, dict] = {}


def get_callback_url() -> str:
    """Return the OAuth callback URL for this gateway."""
    # In Docker, the gateway is behind nginx at /api/
    # The callback needs to be accessible from the user's browser
    host = os.getenv("OAUTH_CALLBACK_HOST", "http://localhost/api")
    return f"{host}/oauth/callback"


def start_flow(server_name: str, oauth_config: dict) -> str:
    """Generate an OAuth authorization URL and return it.

    The admin opens this URL in their browser to authenticate.
    """
    state = secrets.token_urlsafe(32)
    # PKCE code verifier for public clients
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = hashlib.sha256(code_verifier.encode()).hexdigest()

    _pending_flows[state] = {
        "server_name": server_name,
        "code_verifier": code_verifier,
        "token_url": oauth_config["token_url"],
        "client_id": oauth_config.get("client_id", ""),
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
    flow = _pending_flows.pop(state, None)
    if not flow:
        return {"server_name": "unknown", "success": False, "error": "Invalid or expired OAuth state"}

    server_name = flow["server_name"]

    try:
        # Exchange code for token
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
            return {"server_name": server_name, "success": False, "error": f"Token exchange failed: {resp.status_code}"}

        token_data = resp.json()
        access_token = token_data.get("access_token")
        if not access_token:
            return {"server_name": server_name, "success": False, "error": "No access_token in response"}

        # Store the token as a secret
        secret_key = f"oauth_{server_name}"
        if db.is_available():
            await db.set_secret(secret_key, access_token)
            logger.info("Stored OAuth token for MCP server '%s' as secret '%s'", server_name, secret_key)

        return {"server_name": server_name, "success": True, "error": None}

    except Exception as e:
        logger.error("OAuth token exchange failed for '%s': %s", server_name, e)
        return {"server_name": server_name, "success": False, "error": str(e)}
