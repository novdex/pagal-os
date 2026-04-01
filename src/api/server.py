"""PAGAL OS API Server — FastAPI application with web dashboard."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.api.routes import router
from src.core.config import get_config

logger = logging.getLogger("pagal_os")

# Resolve paths relative to the project root
_project_root = Path(__file__).parent.parent.parent
_templates_dir = _project_root / "src" / "web" / "templates"
_static_dir = _project_root / "src" / "web" / "static"


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler — initializes tools and config on startup.

    Args:
        application: The FastAPI application instance.
    """
    import src.tools  # noqa: F401

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

# Mount static files
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# Set up Jinja2 templates
templates = Jinja2Templates(directory=str(_templates_dir))

# Include API routes
app.include_router(router)
