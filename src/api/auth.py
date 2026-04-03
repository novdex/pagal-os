"""PAGAL OS API Authentication & CSRF — bearer token middleware and CSRF tokens.

Protects all /api/* endpoints with a bearer token. Web pages (HTML) and
static files are served without authentication so the dashboard remains
accessible.

The token is read from the PAGAL_API_TOKEN environment variable. When the
variable is not set, authentication is **disabled** and all requests are
allowed (development mode). A warning is logged on startup in this case.

Usage in tests:
    client.get("/api/agents", headers={"Authorization": "Bearer <token>"})
"""

import hashlib
import logging
import os
import secrets

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger("pagal_os")

# ---------------------------------------------------------------------------
# CSRF Token Generation
# ---------------------------------------------------------------------------

# CSRF secret — generated once per server process.
_csrf_secret = os.environ.get("PAGAL_CSRF_SECRET") or secrets.token_urlsafe(32)


def generate_csrf_token(session_id: str = "default") -> str:
    """Generate a CSRF token tied to the server secret."""
    return hashlib.sha256(f"{_csrf_secret}:{session_id}".encode()).hexdigest()[:40]


def verify_csrf_token(token: str, session_id: str = "default") -> bool:
    """Verify a CSRF token."""
    expected = generate_csrf_token(session_id)
    return secrets.compare_digest(token, expected)

# Paths that do NOT require authentication.
_PUBLIC_PREFIXES = (
    "/static/",   # CSS / JS assets
    "/docs",      # Swagger UI
    "/openapi",   # OpenAPI spec
    "/webhooks/", # Inbound webhooks (authenticated separately)
)

# Web pages are served at /, /create, /logs, etc. — all non-/api/ GETs.
# We exempt them so the dashboard stays usable without a token.


def _get_api_token() -> str | None:
    """Return the configured API token, or None if auth is disabled."""
    return os.environ.get("PAGAL_API_TOKEN") or None


def generate_api_token() -> str:
    """Generate a secure random API token (for first-time setup)."""
    return secrets.token_urlsafe(32)


class APIAuthMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that enforces bearer-token auth on /api/* routes.

    When ``PAGAL_API_TOKEN`` is unset the middleware passes all requests
    through (development mode) and logs a warning once.
    """

    _warned: bool = False

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path

        # Always allow public/static paths
        if any(path.startswith(prefix) for prefix in _PUBLIC_PREFIXES):
            return await call_next(request)

        # Allow non-API paths (web pages served by Jinja2)
        if not path.startswith("/api/"):
            return await call_next(request)

        # --- /api/* route — enforce auth ---
        expected_token = _get_api_token()

        if expected_token is None:
            # No token configured — development mode
            if not APIAuthMiddleware._warned:
                logger.warning(
                    "PAGAL_API_TOKEN is not set — API authentication is DISABLED. "
                    "Set the environment variable to secure your API."
                )
                APIAuthMiddleware._warned = True
            return await call_next(request)

        # Validate Authorization header
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"ok": False, "error": "Missing or invalid Authorization header. Use: Bearer <token>"},
            )

        provided_token = auth_header[7:]  # strip "Bearer "
        if not secrets.compare_digest(provided_token, expected_token):
            return JSONResponse(
                status_code=403,
                content={"ok": False, "error": "Invalid API token."},
            )

        return await call_next(request)
