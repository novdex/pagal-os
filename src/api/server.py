"""PAGAL OS API Server — FastAPI application with web dashboard."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from src.api.auth import (
    APIAuthMiddleware,
    generate_csrf_token,
    verify_csrf_token,
)
from src.api.routes import router  # noqa: E402 — routes package (__init__.py)
from src.core.config import get_config

logger = logging.getLogger("pagal_os")

# Resolve paths relative to the project root
_project_root = Path(__file__).parent.parent.parent
_templates_dir = _project_root / "src" / "web" / "templates"
_static_dir = _project_root / "src" / "web" / "static"


# ---------------------------------------------------------------------------
# Security Headers Middleware
# ---------------------------------------------------------------------------


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add standard security headers to every HTTP response."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # HSTS — only effective over HTTPS, but harmless to set unconditionally.
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


# ---------------------------------------------------------------------------
# Request Size Limit Middleware
# ---------------------------------------------------------------------------

# 1 MB max request body size (prevents DoS via giant payloads).
_MAX_REQUEST_BODY_BYTES = 1 * 1024 * 1024


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests with bodies exceeding _MAX_REQUEST_BODY_BYTES."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > _MAX_REQUEST_BODY_BYTES:
            return JSONResponse(
                status_code=413,
                content={
                    "ok": False,
                    "error": f"Request body too large (max {_MAX_REQUEST_BODY_BYTES // 1024}KB).",
                },
            )
        return await call_next(request)


# ---------------------------------------------------------------------------
# CSRF Protection Middleware
# ---------------------------------------------------------------------------

# HTTP methods that mutate state and require CSRF validation.
_CSRF_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Paths exempted from CSRF checks (API endpoints use bearer auth instead).
_CSRF_EXEMPT_PREFIXES = (
    "/api/",      # API routes use bearer-token auth
    "/webhooks/", # Inbound webhooks
)


class CSRFMiddleware(BaseHTTPMiddleware):
    """Middleware that validates CSRF tokens on state-changing requests to web pages.

    API endpoints (/api/*) are exempt — they use bearer-token auth instead.
    Web form submissions (POST to /, /create, /settings, etc.) must include
    an X-CSRF-Token header or _csrf_token form field.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Only check unsafe methods
        if request.method not in _CSRF_UNSAFE_METHODS:
            return await call_next(request)

        path = request.url.path

        # API routes and webhooks use their own auth — skip CSRF
        if any(path.startswith(prefix) for prefix in _CSRF_EXEMPT_PREFIXES):
            return await call_next(request)

        # Check CSRF token in header or form field
        token = request.headers.get("X-CSRF-Token", "")
        if not token:
            # Try query param as fallback (for form submissions)
            token = request.query_params.get("_csrf_token", "")

        if not token or not verify_csrf_token(token):
            return JSONResponse(
                status_code=403,
                content={"ok": False, "error": "CSRF token missing or invalid."},
            )

        return await call_next(request)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler — initializes tools and config on startup.

    Args:
        application: The FastAPI application instance.
    """
    import src.tools  # noqa: F401

    # Initialise all database tables on startup
    try:
        from src.core.database import init_all_tables
        init_all_tables()
    except Exception as e:
        logger.warning("Database init skipped: %s", e)

    config = get_config()

    # Restore scheduled hands from disk
    try:
        from src.core.hands import restore_hands
        restored = restore_hands()
        if restored:
            logger.info("Restored %d hands on startup.", restored)
    except Exception as e:
        logger.warning("Failed to restore hands on startup: %s", e)

    logger.info("PAGAL OS server started on port %d", config.web_port)
    yield

    # Shutdown: stop all hands, MCP, A2A servers
    logger.info("PAGAL OS server shutting down...")
    try:
        from src.core.hands import _active_hands, stop_hand
        for name in list(_active_hands.keys()):
            try:
                stop_hand(name)
            except Exception:
                pass
    except Exception:
        pass

    try:
        from src.core.mcp import stop_mcp_server
        stop_mcp_server()
    except Exception:
        pass

    try:
        from src.core.a2a import stop_a2a_server
        stop_a2a_server()
    except Exception:
        pass

    logger.info("PAGAL OS server shutdown complete.")


# Create FastAPI app
app = FastAPI(
    title="PAGAL OS",
    description="AI Agent Operating System",
    version="0.1.0",
    lifespan=lifespan,
)

# --- Security Middleware ---
# Order matters: outermost middleware runs first (added last).
app.add_middleware(APIAuthMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestSizeLimitMiddleware)

# CORS — restrict to same-origin by default.
# Override via PAGAL_CORS_ORIGINS env var (comma-separated list).
import os as _os
_cors_origins_raw = _os.environ.get("PAGAL_CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()] if _cors_origins_raw else []
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,  # Empty = same-origin only
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
)

# Mount static files
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# Set up Jinja2 templates
templates = Jinja2Templates(directory=str(_templates_dir))

# Include API routes
app.include_router(router)
