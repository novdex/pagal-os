"""Web page routes — all GET routes that serve HTML templates."""

import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from src.core.config import get_config
from src.core.runtime import list_agents

logger = logging.getLogger("pagal_os")

router = APIRouter(tags=["web"])

# Templates (same directory as server.py uses)
_project_root = Path(__file__).parent.parent.parent.parent
_templates_dir = _project_root / "src" / "web" / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

# Expose CSRF token helper to all templates
from src.api.auth import generate_csrf_token
templates.env.globals["csrf_token"] = lambda: generate_csrf_token()


@router.get("/", response_class=HTMLResponse)
async def page_dashboard(request: Request) -> HTMLResponse:
    """Serve the dashboard page.

    Args:
        request: FastAPI request object.

    Returns:
        Rendered HTML dashboard page.
    """
    agents = list_agents()
    return templates.TemplateResponse(request, "dashboard.html", {"agents": agents})


@router.get("/store", response_class=HTMLResponse)
async def page_store(request: Request) -> HTMLResponse:
    """Serve the agent store/marketplace page.

    Args:
        request: FastAPI request object.

    Returns:
        Rendered HTML store page.
    """
    return templates.TemplateResponse(request, "store.html")


@router.get("/create", response_class=HTMLResponse)
async def page_create(request: Request) -> HTMLResponse:
    """Serve the create agent page.

    Args:
        request: FastAPI request object.

    Returns:
        Rendered HTML create page.
    """
    return templates.TemplateResponse(request, "create.html")


@router.get("/logs", response_class=HTMLResponse)
async def page_logs(request: Request) -> HTMLResponse:
    """Serve the logs page.

    Args:
        request: FastAPI request object.

    Returns:
        Rendered HTML logs page.
    """
    agents = list_agents()
    return templates.TemplateResponse(request, "logs.html", {"agents": agents})


@router.get("/builder", response_class=HTMLResponse)
async def page_builder(request: Request) -> HTMLResponse:
    """Serve the visual drag-and-drop agent builder page.

    Args:
        request: FastAPI request object.

    Returns:
        Rendered HTML builder page.
    """
    return templates.TemplateResponse(request, "builder.html")


@router.get("/analytics", response_class=HTMLResponse)
async def page_analytics(request: Request) -> HTMLResponse:
    """Serve the analytics page.

    Args:
        request: FastAPI request object.

    Returns:
        Rendered HTML analytics page.
    """
    return templates.TemplateResponse(request, "analytics.html")


@router.get("/traces", response_class=HTMLResponse)
async def page_traces(request: Request) -> HTMLResponse:
    """Serve the traces page.

    Args:
        request: FastAPI request object.

    Returns:
        Rendered HTML traces page.
    """
    return templates.TemplateResponse(request, "traces.html")


@router.get("/debugger", response_class=HTMLResponse)
async def page_debugger(request: Request) -> HTMLResponse:
    """Serve the agent debugger page.

    Args:
        request: FastAPI request object.

    Returns:
        Rendered HTML debugger page.
    """
    return templates.TemplateResponse(request, "debugger.html")


@router.get("/gallery", response_class=HTMLResponse)
async def page_gallery(request: Request) -> HTMLResponse:
    """Serve the agent templates gallery page.

    Args:
        request: FastAPI request object.

    Returns:
        Rendered HTML gallery page.
    """
    return templates.TemplateResponse(request, "gallery.html")


@router.get("/playground", response_class=HTMLResponse)
async def page_playground(request: Request) -> HTMLResponse:
    """Serve the live agent playground page.

    Args:
        request: FastAPI request object.

    Returns:
        Rendered HTML playground page.
    """
    return templates.TemplateResponse(request, "playground.html")


@router.get("/settings", response_class=HTMLResponse)
async def page_settings(request: Request) -> HTMLResponse:
    """Serve the settings page.

    Args:
        request: FastAPI request object.

    Returns:
        Rendered HTML settings page.
    """
    config = get_config()
    return templates.TemplateResponse(request, "settings.html", {"config": config})


@router.get("/dependencies", response_class=HTMLResponse)
async def page_dependencies(request: Request) -> HTMLResponse:
    """Serve the agent dependency graph visualization page.

    Args:
        request: FastAPI request object.

    Returns:
        Rendered HTML dependencies page.
    """
    return templates.TemplateResponse(request, "dependencies.html")
