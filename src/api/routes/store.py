"""Marketplace, ratings, reviews, and gallery routes."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from src.api.routes._models import RateAgentRequest
from src.core.validators import validate_rating

logger = logging.getLogger("pagal_os")

router = APIRouter(tags=["marketplace"])


@router.get("/api/marketplace")
async def api_marketplace(
    q: str | None = None,
    featured: str | None = None,
) -> dict[str, Any]:
    """List or search marketplace agents.

    Args:
        q: Optional search query.
        featured: If "true", return only featured agents.

    Returns:
        Dict with list of agent entries.
    """
    try:
        from src.core.marketplace import get_featured, list_marketplace, search_marketplace

        if featured and featured.lower() == "true":
            agents = get_featured()
        elif q:
            agents = search_marketplace(q)
        else:
            agents = list_marketplace()
        return {"ok": True, "agents": agents}
    except Exception as e:
        logger.error("Marketplace API error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/marketplace/install/{agent_id}")
async def api_marketplace_install(agent_id: str) -> dict[str, Any]:
    """Install an agent from the marketplace.

    Args:
        agent_id: Marketplace agent ID.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.marketplace import install_agent

        if install_agent(agent_id):
            return {"ok": True, "message": f"Agent '{agent_id}' installed"}
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found or install failed")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Marketplace install error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/marketplace/{agent_id}/rate")
async def api_rate_agent(agent_id: str, req: RateAgentRequest) -> dict[str, Any]:
    """Rate a marketplace agent with 1-5 stars and optional review.

    Args:
        agent_id: Marketplace agent ID.
        req: Request with rating (1-5) and optional review text.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.marketplace import rate_agent

        valid, err = validate_rating(req.rating)
        if not valid:
            raise HTTPException(status_code=400, detail=err)

        if rate_agent(agent_id, req.rating, req.review):
            return {"ok": True, "message": f"Agent '{agent_id}' rated {req.rating} stars"}
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Rate agent error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/marketplace/{agent_id}/reviews")
async def api_get_reviews(agent_id: str) -> dict[str, Any]:
    """Get all reviews for a marketplace agent.

    Args:
        agent_id: Marketplace agent ID.

    Returns:
        Dict with list of review entries.
    """
    try:
        from src.core.marketplace import get_reviews

        reviews = get_reviews(agent_id)
        return {"ok": True, "agent_id": agent_id, "reviews": reviews}
    except Exception as e:
        logger.error("Get reviews error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/marketplace/top-rated")
async def api_top_rated(limit: int = 10) -> dict[str, Any]:
    """Get top-rated agents from the marketplace.

    Args:
        limit: Max number of agents to return.

    Returns:
        Dict with list of top-rated agent entries.
    """
    try:
        from src.core.marketplace import get_top_rated

        agents = get_top_rated(limit)
        return {"ok": True, "agents": agents}
    except Exception as e:
        logger.error("Top rated error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
