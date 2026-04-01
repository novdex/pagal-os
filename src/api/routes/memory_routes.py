"""Memory and knowledge routes: knowledge graph, cross-session memory, MCP,
A2A, audit, usage, approvals, registry, rate-limits, model routing.

Split from system.py for maintainability.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from src.api.routes._models import (
    SetRateLimitRequest,
    UpdatePermissionsRequest,
)

logger = logging.getLogger("pagal_os")

router = APIRouter()


# --- Knowledge ---


@router.get("/api/knowledge", tags=["knowledge"])
async def api_knowledge_search(
    query: str = "",
    agent: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Search the knowledge graph.

    Args:
        query: Search string.
        agent: Optional agent name filter.
        limit: Max results.

    Returns:
        Dict with matching knowledge nodes.
    """
    try:
        from src.core.knowledge import search_knowledge

        results = search_knowledge(query, agent_name=agent, limit=limit)
        return {"ok": True, "results": results}
    except Exception as e:
        logger.error("Knowledge search error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/knowledge/stats", tags=["knowledge"])
async def api_knowledge_stats() -> dict[str, Any]:
    """Get knowledge graph statistics.

    Returns:
        Dict with node/edge/topic counts.
    """
    try:
        from src.core.knowledge import get_stats

        return get_stats()
    except Exception as e:
        logger.error("Knowledge stats error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Memory ---


@router.get("/api/memory", tags=["memory"])
async def api_memory_stats(agent: str | None = None) -> dict[str, Any]:
    """Get cross-session memory statistics.

    Args:
        agent: Optional agent name to filter by.

    Returns:
        Dict with memory stats.
    """
    try:
        from src.core.memory import get_memory_stats
        return {"ok": True, **get_memory_stats(agent)}
    except Exception as e:
        logger.error("Memory stats error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/memory/search", tags=["memory"])
async def api_memory_search(agent: str, query: str, limit: int = 10) -> dict[str, Any]:
    """Search an agent's cross-session memory.

    Args:
        agent: Agent name.
        query: Search keywords.
        limit: Max results.

    Returns:
        Dict with search results.
    """
    try:
        from src.core.memory import search_memory
        results = search_memory(agent, query, limit)
        return {"ok": True, "results": results}
    except Exception as e:
        logger.error("Memory search error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Audit ---


@router.get("/api/audit", tags=["security"])
async def api_audit_log(limit: int = 100) -> dict[str, Any]:
    """Get recent audit log entries.

    Args:
        limit: Max number of entries (newest first).

    Returns:
        Dict with log entries.
    """
    try:
        from src.core.security import get_audit_entries

        entries = get_audit_entries(limit=limit)
        return {"ok": True, "entries": entries}
    except Exception as e:
        logger.error("Audit log API error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Usage ---


@router.get("/api/usage", tags=["usage"])
async def api_usage_report(agent: str | None = None) -> dict[str, Any]:
    """Get resource usage report for agents.

    Args:
        agent: Optional agent name to filter by.

    Returns:
        Dict with usage statistics.
    """
    try:
        from src.core.resources import get_usage_report
        return get_usage_report(agent)
    except Exception as e:
        logger.error("Failed to get usage report: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Approvals ---


@router.get("/api/approvals", tags=["approvals"])
async def api_get_approvals() -> dict[str, Any]:
    """List all pending approval requests.

    Returns:
        Dict with list of pending approval entries.
    """
    try:
        from src.core.approval import get_pending_approvals

        approvals = get_pending_approvals()
        return {"ok": True, "approvals": approvals}
    except Exception as e:
        logger.error("Get approvals error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/approvals/{approval_id}/approve", tags=["approvals"])
async def api_approve_action(approval_id: str) -> dict[str, Any]:
    """Approve a pending action.

    Args:
        approval_id: The approval request ID.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.approval import approve

        if approve(approval_id):
            return {"ok": True, "message": f"Approval {approval_id} granted"}
        raise HTTPException(status_code=404, detail=f"Approval '{approval_id}' not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Approve error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/approvals/{approval_id}/deny", tags=["approvals"])
async def api_deny_action(approval_id: str) -> dict[str, Any]:
    """Deny a pending action.

    Args:
        approval_id: The approval request ID.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.approval import deny

        if deny(approval_id):
            return {"ok": True, "message": f"Approval {approval_id} denied"}
        raise HTTPException(status_code=404, detail=f"Approval '{approval_id}' not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Deny error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Model Routing ---


@router.get("/api/routing/stats", tags=["routing"])
async def api_routing_stats() -> dict[str, Any]:
    """Get model routing statistics.

    Returns:
        Dict with routing tier counts and model assignments.
    """
    try:
        from src.core.model_router import get_routing_stats
        return {"ok": True, **get_routing_stats()}
    except Exception as e:
        logger.error("Routing stats error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Registry ---


@router.get("/api/registry", tags=["registry"])
async def api_list_registry() -> dict[str, Any]:
    """List all registered agents with their identities.

    Returns:
        Dict with list of agent identity records.
    """
    try:
        from src.core.registry import list_registered
        agents = list_registered()
        return {"ok": True, "agents": agents}
    except Exception as e:
        logger.error("Registry list error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/registry/{agent_name}", tags=["registry"])
async def api_get_registry_agent(agent_name: str) -> dict[str, Any]:
    """Get identity and permissions for a specific agent.

    Args:
        agent_name: Agent name.

    Returns:
        Dict with agent identity record.
    """
    try:
        from src.core.registry import get_agent_identity
        identity = get_agent_identity(agent_name)
        if not identity:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not registered")
        return {"ok": True, **identity}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Registry get error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/registry/{agent_name}/permissions", tags=["registry"])
async def api_update_permissions(agent_name: str, req: UpdatePermissionsRequest) -> dict[str, Any]:
    """Update permissions for a registered agent.

    Args:
        agent_name: Agent name.
        req: Request with permissions dict.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.registry import update_permissions
        if update_permissions(agent_name, req.permissions):
            return {"ok": True, "message": f"Permissions updated for '{agent_name}'"}
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not registered")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Registry permissions error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Rate Limits ---


@router.get("/api/rate-limits", tags=["rate-limits"])
async def api_get_rate_limits(agent: str | None = None) -> dict[str, Any]:
    """Get rate limit config and usage for one or all agents.

    Args:
        agent: Optional agent name. If omitted, returns all.

    Returns:
        Dict with rate limit details.
    """
    try:
        from src.core.rate_limiter import get_rate_limits, get_rate_stats

        limits = get_rate_limits(agent)
        stats = get_rate_stats()
        return {"ok": True, "limits": limits, "stats": stats}
    except Exception as e:
        logger.error("Rate limits error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/rate-limits/{agent_name}", tags=["rate-limits"])
async def api_set_rate_limit(
    agent_name: str, req: SetRateLimitRequest,
) -> dict[str, Any]:
    """Set custom rate limits for an agent.

    Args:
        agent_name: Agent name.
        req: Request with per_minute and per_hour limits.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.rate_limiter import set_rate_limit

        set_rate_limit(agent_name, req.per_minute, req.per_hour)
        return {
            "ok": True,
            "message": f"Rate limit set for '{agent_name}': {req.per_minute}/min, {req.per_hour}/hr",
        }
    except Exception as e:
        logger.error("Set rate limit error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
