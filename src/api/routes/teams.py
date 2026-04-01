"""Team CRUD and run routes."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from src.api.routes._models import CreateTeamRequest, RunTeamRequest

logger = logging.getLogger("pagal_os")

router = APIRouter(tags=["teams"])


@router.post("/api/teams")
async def api_create_team(req: CreateTeamRequest) -> dict[str, Any]:
    """Create a multi-agent team.

    Args:
        req: Request with team name, agents, coordinator, and goal.

    Returns:
        Dict with team info.
    """
    try:
        from src.core.collaboration import create_team
        result = create_team(req.name, req.agents, req.coordinator, req.goal)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create team: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/teams")
async def api_list_teams() -> dict[str, Any]:
    """List all defined teams.

    Returns:
        Dict with list of team info dicts.
    """
    try:
        from src.core.collaboration import list_teams
        teams = list_teams()
        return {"ok": True, "teams": teams}
    except Exception as e:
        logger.error("Failed to list teams: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/teams/{name}/run")
async def api_run_team(name: str, req: RunTeamRequest) -> dict[str, Any]:
    """Run a team task.

    Args:
        name: Team name.
        req: Request with task.

    Returns:
        Dict with team execution results.
    """
    try:
        from src.core.collaboration import run_team
        result = run_team(name, req.task)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to run team '%s': %s", name, e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/api/teams/{name}")
async def api_delete_team(name: str) -> dict[str, Any]:
    """Delete a team.

    Args:
        name: Team name.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.collaboration import delete_team
        if delete_team(name):
            return {"ok": True, "message": f"Team '{name}' deleted"}
        raise HTTPException(status_code=404, detail=f"Team '{name}' not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to delete team '%s': %s", name, e)
        raise HTTPException(status_code=500, detail=str(e)) from e
