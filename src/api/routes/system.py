"""System routes: health, budget, analytics, traces, notifications, credits,
processes.

Knowledge, memory, audit, approvals, registry, rate-limits, and routing
endpoints are in memory_routes.py. Workflows, goals, debug, batches, and
worlds endpoints are in automation.py.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

logger = logging.getLogger("pagal_os")

router = APIRouter()


# --- Health ---


@router.get("/api/health", tags=["health"])
async def api_health_dashboard() -> dict[str, Any]:
    """Get system-wide agent health dashboard.

    Returns:
        Dict with total_agents, healthy/degraded/dead counts, and per-agent status.
    """
    try:
        from src.core.health import get_health_dashboard
        return get_health_dashboard()
    except Exception as e:
        logger.error("Health dashboard error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/health/{agent_name}", tags=["health"])
async def api_health_agent(agent_name: str) -> dict[str, Any]:
    """Get health status of a specific agent.

    Args:
        agent_name: The agent to check.

    Returns:
        Dict with agent health status, uptime, restart count, etc.
    """
    try:
        from src.core.health import check_health
        health = check_health(agent_name)
        return {
            "agent_name": health.agent_name,
            "status": health.status,
            "last_heartbeat": health.last_heartbeat,
            "uptime_seconds": round(health.uptime_seconds, 1),
            "restart_count": health.restart_count,
            "errors_last_hour": health.errors_last_hour,
        }
    except Exception as e:
        logger.error("Health check error for '%s': %s", agent_name, e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Budget ---


@router.get("/api/budget", tags=["budget"])
async def api_budget_all() -> dict[str, Any]:
    """Get budget status for all agents.

    Returns:
        Dict with spending report.
    """
    try:
        from src.core.budget import get_spending_report
        return {"ok": True, **get_spending_report()}
    except Exception as e:
        logger.error("Budget report error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/budget/{agent_name}", tags=["budget"])
async def api_budget_agent(agent_name: str) -> dict[str, Any]:
    """Get budget status for a specific agent.

    Args:
        agent_name: Agent name.

    Returns:
        Dict with budget check results.
    """
    try:
        from src.core.budget import check_budget
        return {"ok": True, **check_budget(agent_name)}
    except Exception as e:
        logger.error("Budget check error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Analytics ---


@router.get("/api/analytics", tags=["analytics"])
async def api_all_analytics(days: int = 30) -> dict[str, Any]:
    """Get system-wide analytics.

    Args:
        days: Number of days to look back.

    Returns:
        Dict with total runs, success rate, tokens, cost, and per-agent breakdown.
    """
    try:
        from src.core.analytics import get_all_analytics

        return {"ok": True, **get_all_analytics(days)}
    except Exception as e:
        logger.error("Analytics error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/analytics/{agent_name}", tags=["analytics"])
async def api_agent_analytics(agent_name: str, days: int = 30) -> dict[str, Any]:
    """Get analytics for a specific agent.

    Args:
        agent_name: Agent name.
        days: Number of days to look back.

    Returns:
        Dict with agent-specific analytics.
    """
    try:
        from src.core.analytics import get_agent_analytics

        return {"ok": True, **get_agent_analytics(agent_name, days)}
    except Exception as e:
        logger.error("Agent analytics error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Traces ---


@router.get("/api/traces", tags=["traces"])
async def api_list_traces(
    agent: str | None = None,
    limit: int = 30,
) -> dict[str, Any]:
    """List recent traces, optionally filtered by agent.

    Args:
        agent: Optional agent name filter.
        limit: Max number of traces.

    Returns:
        Dict with list of trace summaries.
    """
    try:
        from src.core.observability import get_recent_traces
        traces = get_recent_traces(agent_name=agent, limit=limit)
        return {"ok": True, "traces": traces}
    except Exception as e:
        logger.error("List traces error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/traces/{run_id}", tags=["traces"])
async def api_get_trace(run_id: str) -> dict[str, Any]:
    """Get all events for a specific trace run.

    Args:
        run_id: The run ID.

    Returns:
        Dict with list of events.
    """
    try:
        from src.core.observability import get_trace
        events = get_trace(run_id)
        if not events:
            raise HTTPException(status_code=404, detail=f"Trace '{run_id}' not found")
        return {"ok": True, "run_id": run_id, "events": events}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Get trace error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/traces/{run_id}/summary", tags=["traces"])
async def api_trace_summary(run_id: str) -> dict[str, Any]:
    """Get a summary of a trace run.

    Args:
        run_id: The run ID.

    Returns:
        Dict with summary stats.
    """
    try:
        from src.core.observability import get_trace_summary
        result = get_trace_summary(run_id)
        if not result.get("ok"):
            raise HTTPException(status_code=404, detail=result.get("error", "Not found"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Trace summary error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Notifications ---


@router.get("/api/notifications", tags=["notifications"])
async def api_get_notifications(
    unread_only: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """Get notifications, optionally filtered to unread only.

    Args:
        unread_only: If true, return only unread notifications.
        limit: Max number of notifications.

    Returns:
        Dict with notifications list and unread count.
    """
    try:
        from src.core.notifications import get_notifications, get_unread_count
        notifications = get_notifications(unread_only=unread_only, limit=limit)
        unread = get_unread_count()
        return {"ok": True, "notifications": notifications, "unread_count": unread}
    except Exception as e:
        logger.error("Notifications error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/notifications/{notification_id}/read", tags=["notifications"])
async def api_mark_notification_read(notification_id: str) -> dict[str, Any]:
    """Mark a notification as read.

    Args:
        notification_id: The notification ID.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.notifications import mark_read
        if mark_read(notification_id):
            return {"ok": True, "message": f"Notification {notification_id} marked read"}
        raise HTTPException(status_code=404, detail=f"Notification '{notification_id}' not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Mark read error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/notifications/read-all", tags=["notifications"])
async def api_mark_all_notifications_read() -> dict[str, Any]:
    """Mark all notifications as read.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.notifications import mark_all_read
        mark_all_read()
        return {"ok": True, "message": "All notifications marked read"}
    except Exception as e:
        logger.error("Mark all read error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Credits ---


@router.get("/api/credits", tags=["credits"])
async def api_get_credits(user_id: str = "local") -> dict[str, Any]:
    """Get credit balance for a user.

    Args:
        user_id: User identifier (default 'local').

    Returns:
        Dict with balance.
    """
    try:
        from src.core.credits import get_balance
        balance = get_balance(user_id)
        return {"ok": True, "user_id": user_id, "balance": balance}
    except Exception as e:
        logger.error("Credits balance error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/credits/transactions", tags=["credits"])
async def api_get_transactions(user_id: str = "local", limit: int = 50) -> dict[str, Any]:
    """Get credit transaction history.

    Args:
        user_id: User identifier.
        limit: Max number of transactions.

    Returns:
        Dict with transaction list.
    """
    try:
        from src.core.credits import get_balance, get_transactions
        transactions = get_transactions(user_id, limit)
        balance = get_balance(user_id)
        return {"ok": True, "balance": balance, "transactions": transactions}
    except Exception as e:
        logger.error("Credits transactions error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Processes ---


@router.get("/api/processes", tags=["processes"])
async def api_list_processes() -> dict[str, Any]:
    """List all agent processes (like ps aux).

    Returns:
        Dict with list of process info dicts and system stats.
    """
    try:
        from src.core.process_manager import get_system_stats, list_processes
        processes = list_processes()
        stats = get_system_stats()
        return {"ok": True, "processes": processes, "system": stats}
    except Exception as e:
        logger.error("Process list error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/processes/{pid}", tags=["processes"])
async def api_get_process(pid: str) -> dict[str, Any]:
    """Get details for a single process.

    Args:
        pid: Process ID.

    Returns:
        Dict with process info.
    """
    try:
        from src.core.process_manager import get_process_stats
        result = get_process_stats(pid)
        if not result.get("ok"):
            raise HTTPException(status_code=404, detail=f"Process {pid} not found")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Process stats error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/api/processes/{pid}", tags=["processes"])
async def api_kill_process(pid: str) -> dict[str, Any]:
    """Kill an agent process.

    Args:
        pid: Process ID.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.process_manager import kill_process
        if kill_process(pid):
            return {"ok": True, "message": f"Process {pid} killed"}
        raise HTTPException(status_code=404, detail=f"Process {pid} not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Process kill error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
