"""Hands (scheduled agent tasks) start/stop/list routes."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from src.api.routes._models import StartHandRequest
from src.core.validators import validate_agent_name, validate_task

logger = logging.getLogger("pagal_os")

router = APIRouter(tags=["hands"])


@router.post("/api/hands")
async def api_start_hand(req: StartHandRequest) -> dict[str, Any]:
    """Start a scheduled autonomous hand.

    Args:
        req: Request with agent name, schedule, and task.

    Returns:
        Dict with status info.
    """
    try:
        from src.core.hands import start_hand

        valid, err = validate_agent_name(req.agent)
        if not valid:
            raise HTTPException(status_code=400, detail=err)
        valid, err = validate_task(req.task)
        if not valid:
            raise HTTPException(status_code=400, detail=err)

        result = start_hand(req.agent, req.schedule, req.task)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to start hand: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/hands")
async def api_list_hands() -> dict[str, Any]:
    """List all active hands.

    Returns:
        Dict with list of hand info dicts.
    """
    try:
        from src.core.hands import list_hands
        hands = list_hands()
        return {"ok": True, "hands": hands}
    except Exception as e:
        logger.error("Failed to list hands: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/api/hands/{name}")
async def api_stop_hand(name: str) -> dict[str, Any]:
    """Stop a scheduled hand.

    Args:
        name: Agent/hand name.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.hands import stop_hand
        if stop_hand(name):
            return {"ok": True, "message": f"Hand '{name}' stopped"}
        raise HTTPException(status_code=404, detail=f"Hand '{name}' not found or not running")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to stop hand '%s': %s", name, e)
        raise HTTPException(status_code=500, detail=str(e)) from e
