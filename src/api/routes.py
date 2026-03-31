"""PAGAL OS API Routes — all REST endpoints and web page routes."""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from src.core.config import get_config
from src.core.creator import create_agent_from_description
from src.core.runtime import (
    delete_agent,
    get_agent_status,
    list_agents,
    load_agent,
    run_agent_async,
    stop_agent,
)
from src.core.sandbox import run_in_sandbox

logger = logging.getLogger("pagal_os")

router = APIRouter()

# Templates (same directory as server.py uses)
_project_root = Path(__file__).parent.parent.parent
_templates_dir = _project_root / "src" / "web" / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


# --- Pydantic models for request bodies ---


class CreateAgentRequest(BaseModel):
    """Request body for creating an agent."""

    description: str
    model: str | None = None


class RunAgentRequest(BaseModel):
    """Request body for running an agent."""

    task: str
    async_mode: bool = False


class SettingsUpdate(BaseModel):
    """Request body for updating settings."""

    openrouter_api_key: str | None = None
    default_model: str | None = None
    ollama_url: str | None = None


# --- API Endpoints ---


@router.post("/api/agents", tags=["agents"])
async def api_create_agent(req: CreateAgentRequest) -> dict[str, Any]:
    """Create a new agent from a natural language description.

    Args:
        req: Request with description and optional model.

    Returns:
        Dict with agent name and success status.
    """
    try:
        name = create_agent_from_description(req.description, req.model)
        return {"ok": True, "name": name, "message": f"Agent '{name}' created"}
    except Exception as e:
        logger.error("Failed to create agent: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/agents", tags=["agents"])
async def api_list_agents() -> dict[str, Any]:
    """List all available agents.

    Returns:
        Dict with list of agent info dicts.
    """
    try:
        agents = list_agents()
        return {"ok": True, "agents": agents}
    except Exception as e:
        logger.error("Failed to list agents: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/agents/{name}/run", tags=["agents"])
async def api_run_agent(name: str, req: RunAgentRequest) -> dict[str, Any]:
    """Run an agent with a given task.

    Args:
        name: Agent name.
        req: Request with task and optional async_mode flag.

    Returns:
        AgentResult as dict if synchronous, or status message if async.
    """
    try:
        if req.async_mode:
            result = run_agent_async(name, req.task)
            return {"ok": True, **result}

        agent = load_agent(name)
        result = run_in_sandbox(agent, req.task)
        return {
            "ok": result.ok,
            "output": result.output,
            "tools_used": result.tools_used,
            "duration_seconds": result.duration_seconds,
            "error": result.error,
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    except Exception as e:
        logger.error("Failed to run agent '%s': %s", name, e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/agents/{name}/status", tags=["agents"])
async def api_agent_status(name: str) -> dict[str, Any]:
    """Get the status of an agent.

    Args:
        name: Agent name.

    Returns:
        Dict with agent status info.
    """
    try:
        status = get_agent_status(name)
        return {"ok": True, "name": name, **status}
    except Exception as e:
        logger.error("Failed to get status for '%s': %s", name, e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/api/agents/{name}", tags=["agents"])
async def api_delete_agent(name: str) -> dict[str, Any]:
    """Delete an agent.

    Args:
        name: Agent name.

    Returns:
        Dict with success status.
    """
    if delete_agent(name):
        return {"ok": True, "message": f"Agent '{name}' deleted"}
    raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")


@router.post("/api/agents/{name}/stop", tags=["agents"])
async def api_stop_agent(name: str) -> dict[str, Any]:
    """Stop a running agent.

    Args:
        name: Agent name.

    Returns:
        Dict with success status.
    """
    if stop_agent(name):
        return {"ok": True, "message": f"Agent '{name}' stopped"}
    return {"ok": False, "message": f"Agent '{name}' is not running"}


@router.get("/api/agents/{name}/logs", tags=["agents"])
async def api_agent_logs(name: str) -> dict[str, Any]:
    """Get logs for an agent.

    Args:
        name: Agent name.

    Returns:
        Dict with log entries.
    """
    config = get_config()
    log_file = config.logs_dir / f"{name}.log"

    if not log_file.exists():
        return {"ok": True, "logs": [], "message": "No logs yet"}

    try:
        lines = log_file.read_text(encoding="utf-8").strip().split("\n")
        # Return last 100 lines
        return {"ok": True, "logs": lines[-100:]}
    except Exception as e:
        logger.error("Failed to read logs for '%s': %s", name, e)
        return {"ok": False, "logs": [], "error": str(e)}


@router.post("/api/settings", tags=["settings"])
async def api_update_settings(req: SettingsUpdate) -> dict[str, Any]:
    """Update runtime settings.

    Args:
        req: Settings to update.

    Returns:
        Dict with success status.
    """
    import os

    if req.openrouter_api_key is not None:
        os.environ["OPENROUTER_API_KEY"] = req.openrouter_api_key

    config = get_config()
    if req.default_model is not None:
        config.default_model = req.default_model
    if req.ollama_url is not None:
        config.ollama_url = req.ollama_url

    return {"ok": True, "message": "Settings updated"}


# --- Web Page Routes ---


@router.get("/", response_class=HTMLResponse, tags=["web"])
async def page_dashboard(request: Request) -> HTMLResponse:
    """Serve the dashboard page.

    Args:
        request: FastAPI request object.

    Returns:
        Rendered HTML dashboard page.
    """
    agents = list_agents()
    return templates.TemplateResponse(request, "dashboard.html", {"agents": agents})


@router.get("/create", response_class=HTMLResponse, tags=["web"])
async def page_create(request: Request) -> HTMLResponse:
    """Serve the create agent page.

    Args:
        request: FastAPI request object.

    Returns:
        Rendered HTML create page.
    """
    return templates.TemplateResponse(request, "create.html")


@router.get("/logs", response_class=HTMLResponse, tags=["web"])
async def page_logs(request: Request) -> HTMLResponse:
    """Serve the logs page.

    Args:
        request: FastAPI request object.

    Returns:
        Rendered HTML logs page.
    """
    agents = list_agents()
    return templates.TemplateResponse(request, "logs.html", {"agents": agents})


@router.get("/settings", response_class=HTMLResponse, tags=["web"])
async def page_settings(request: Request) -> HTMLResponse:
    """Serve the settings page.

    Args:
        request: FastAPI request object.

    Returns:
        Rendered HTML settings page.
    """
    config = get_config()
    return templates.TemplateResponse(request, "settings.html", {"config": config})
