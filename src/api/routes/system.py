"""System routes: health, budget, analytics, traces, notifications, credits,
processes, approvals, knowledge, memory, audit, usage, rate-limits, registry,
goals, debug, batches, workflows, worlds, routing.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from src.api.routes._models import (
    CreateBatchRequest,
    CreateWorkflowRequest,
    ModifyContextRequest,
    RunBatchRequest,
    RunWorkflowRequest,
    SetBreakpointRequest,
    SetGoalRequest,
    SetRateLimitRequest,
    StartDebugRequest,
    UpdatePermissionsRequest,
)

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


# --- Workflows ---


@router.post("/api/workflows", tags=["workflows"])
async def api_create_workflow(req: CreateWorkflowRequest) -> dict[str, Any]:
    """Create a workflow from a natural language description.

    Args:
        req: Request with description.

    Returns:
        Dict with workflow definition.
    """
    try:
        from src.core.workflows import Workflow, create_workflow_from_description, save_workflow

        result = create_workflow_from_description(req.description)
        if not result["ok"]:
            raise HTTPException(status_code=400, detail=result.get("message", "Failed"))

        # Save to disk
        wf_data = result["workflow"]
        workflow = Workflow(
            name=wf_data["name"],
            trigger=wf_data["trigger"],
            steps=wf_data["steps"],
            description=wf_data["description"],
        )
        save_workflow(workflow)

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Create workflow error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/workflows", tags=["workflows"])
async def api_list_workflows() -> dict[str, Any]:
    """List all saved workflows.

    Returns:
        Dict with list of workflow summaries.
    """
    try:
        from src.core.workflows import list_workflows
        return {"ok": True, "workflows": list_workflows()}
    except Exception as e:
        logger.error("List workflows error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/workflows/{name}/run", tags=["workflows"])
async def api_run_workflow(name: str, req: RunWorkflowRequest) -> dict[str, Any]:
    """Run a saved workflow.

    Args:
        name: Workflow name.
        req: Request with optional input_data.

    Returns:
        Dict with workflow execution results.
    """
    try:
        from src.core.workflows import load_workflow, run_workflow

        workflow = load_workflow(name)
        result = run_workflow(workflow, req.input_data)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Workflow '{name}' not found")
    except Exception as e:
        logger.error("Run workflow error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Goals ---


@router.post("/api/goals", tags=["goals"])
async def api_set_goal(req: SetGoalRequest) -> dict[str, Any]:
    """Set a long-term goal for an agent.

    Args:
        req: Request with agent_name and goal.

    Returns:
        Dict with goal_id and status.
    """
    try:
        from src.core.goals import get_goal_status, set_goal

        goal_id = set_goal(req.agent_name, req.goal)
        status = get_goal_status(goal_id)
        return {"ok": True, "goal_id": goal_id, **status}
    except Exception as e:
        logger.error("Set goal error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/goals", tags=["goals"])
async def api_list_goals(agent: str | None = None) -> dict[str, Any]:
    """List all goals, optionally filtered by agent.

    Args:
        agent: Optional agent name filter.

    Returns:
        Dict with list of goal summaries.
    """
    try:
        from src.core.goals import list_goals
        return {"ok": True, "goals": list_goals(agent)}
    except Exception as e:
        logger.error("List goals error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/goals/{goal_id}", tags=["goals"])
async def api_goal_status(goal_id: int) -> dict[str, Any]:
    """Get status and progress of a specific goal.

    Args:
        goal_id: The goal ID.

    Returns:
        Dict with goal details and progress.
    """
    try:
        from src.core.goals import get_goal_status
        result = get_goal_status(goal_id)
        if not result.get("ok"):
            raise HTTPException(status_code=404, detail=result.get("error", "Not found"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Goal status error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/goals/{goal_id}/work", tags=["goals"])
async def api_work_on_goal(goal_id: int) -> dict[str, Any]:
    """Work on the next sub-task of a goal.

    Args:
        goal_id: The goal ID.

    Returns:
        Dict with work result and updated progress.
    """
    try:
        from src.core.goals import work_on_goal
        return work_on_goal(goal_id)
    except Exception as e:
        logger.error("Work on goal error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/goals/{goal_id}/pause", tags=["goals"])
async def api_pause_goal(goal_id: int) -> dict[str, Any]:
    """Pause an active goal.

    Args:
        goal_id: The goal ID.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.goals import pause_goal
        if pause_goal(goal_id):
            return {"ok": True, "message": f"Goal #{goal_id} paused"}
        raise HTTPException(status_code=404, detail=f"Goal #{goal_id} not found or not active")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Pause goal error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/goals/{goal_id}/resume", tags=["goals"])
async def api_resume_goal(goal_id: int) -> dict[str, Any]:
    """Resume a paused goal.

    Args:
        goal_id: The goal ID.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.goals import resume_goal
        if resume_goal(goal_id):
            return {"ok": True, "message": f"Goal #{goal_id} resumed"}
        raise HTTPException(status_code=404, detail=f"Goal #{goal_id} not found or not paused")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Resume goal error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Debug ---


@router.post("/api/debug/start", tags=["debugger"])
async def api_debug_start(req: StartDebugRequest) -> dict[str, Any]:
    """Start a new debug session for an agent.

    Args:
        req: Request with agent_name and task.

    Returns:
        Dict with session_id.
    """
    try:
        from src.core.debugger import start_debug_session
        session_id = start_debug_session(req.agent_name, req.task)
        return {"ok": True, "session_id": session_id}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent '{req.agent_name}' not found")
    except Exception as e:
        logger.error("Debug start error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/debug/{session_id}/step", tags=["debugger"])
async def api_debug_step(session_id: str) -> dict[str, Any]:
    """Execute one step in a debug session.

    Args:
        session_id: The debug session ID.

    Returns:
        Dict with step result and state.
    """
    try:
        from src.core.debugger import step
        return step(session_id)
    except Exception as e:
        logger.error("Debug step error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/debug/{session_id}/inspect", tags=["debugger"])
async def api_debug_inspect(session_id: str) -> dict[str, Any]:
    """Inspect current state of a debug session.

    Args:
        session_id: The debug session ID.

    Returns:
        Dict with complete current state.
    """
    try:
        from src.core.debugger import inspect
        result = inspect(session_id)
        if not result.get("ok"):
            raise HTTPException(status_code=404, detail=result.get("error", "Not found"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Debug inspect error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/debug/{session_id}/continue", tags=["debugger"])
async def api_debug_continue(session_id: str) -> dict[str, Any]:
    """Continue running until next breakpoint or completion.

    Args:
        session_id: The debug session ID.

    Returns:
        Dict with final state after stopping.
    """
    try:
        from src.core.debugger import continue_debug
        return continue_debug(session_id)
    except Exception as e:
        logger.error("Debug continue error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/debug/{session_id}/breakpoint", tags=["debugger"])
async def api_debug_breakpoint(session_id: str, req: SetBreakpointRequest) -> dict[str, Any]:
    """Set a breakpoint in a debug session.

    Args:
        session_id: The debug session ID.
        req: Request with breakpoint type.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.debugger import set_breakpoint
        if set_breakpoint(session_id, req.on):
            return {"ok": True, "message": f"Breakpoint set on: {req.on}"}
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Debug breakpoint error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/debug/{session_id}/context", tags=["debugger"])
async def api_debug_modify_context(session_id: str, req: ModifyContextRequest) -> dict[str, Any]:
    """Inject a message into a debug session's conversation.

    Args:
        session_id: The debug session ID.
        req: Request with message to inject.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.debugger import modify_context
        if modify_context(session_id, req.message):
            return {"ok": True, "message": "Context modified"}
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Debug context error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/debug/{session_id}/log", tags=["debugger"])
async def api_debug_log(session_id: str) -> dict[str, Any]:
    """Get the full debug log for a session.

    Args:
        session_id: The debug session ID.

    Returns:
        Dict with log entries.
    """
    try:
        from src.core.debugger import get_debug_log
        log = get_debug_log(session_id)
        return {"ok": True, "log": log}
    except Exception as e:
        logger.error("Debug log error: %s", e)
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


# --- Batches ---


@router.post("/api/batches", tags=["batches"])
async def api_create_batch(req: CreateBatchRequest) -> dict[str, Any]:
    """Create a new batch job.

    Args:
        req: Request with agent_name and list of task items.

    Returns:
        Dict with batch_id and item count.
    """
    try:
        from src.core.batch import create_batch
        batch_id = create_batch(req.agent_name, req.items)
        return {"ok": True, "batch_id": batch_id, "items_count": len(req.items)}
    except Exception as e:
        logger.error("Batch creation error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/batches/{batch_id}/run", tags=["batches"])
async def api_run_batch(batch_id: str, req: RunBatchRequest | None = None) -> dict[str, Any]:
    """Run a batch job (sequential or parallel).

    Args:
        batch_id: The batch job ID.
        req: Optional request body with parallel mode and worker count.

    Returns:
        Dict with completion summary.
    """
    try:
        from src.core.batch import run_batch, run_batch_parallel

        if req and req.parallel:
            return run_batch_parallel(batch_id, workers=req.workers)
        return run_batch(batch_id)
    except Exception as e:
        logger.error("Batch run error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/batches", tags=["batches"])
async def api_list_batches() -> dict[str, Any]:
    """List all batch jobs.

    Returns:
        Dict with list of batch job summaries.
    """
    try:
        from src.core.batch import list_batches
        return {"ok": True, "batches": list_batches()}
    except Exception as e:
        logger.error("Batch list error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/batches/{batch_id}", tags=["batches"])
async def api_batch_status(batch_id: str) -> dict[str, Any]:
    """Get the status of a specific batch job.

    Args:
        batch_id: The batch job ID.

    Returns:
        Dict with batch status, progress, and completion info.
    """
    try:
        from src.core.batch import get_batch_status
        return get_batch_status(batch_id)
    except Exception as e:
        logger.error("Batch status error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/api/batches/{batch_id}", tags=["batches"])
async def api_cancel_batch(batch_id: str) -> dict[str, Any]:
    """Cancel a running or queued batch job.

    Args:
        batch_id: The batch job ID to cancel.

    Returns:
        Dict with cancellation status.
    """
    try:
        from src.core.batch import cancel_batch
        if cancel_batch(batch_id):
            return {"ok": True, "message": f"Batch '{batch_id}' cancelled"}
        raise HTTPException(status_code=404, detail=f"Batch '{batch_id}' not found or already completed")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Batch cancel error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Worlds ---


@router.get("/api/worlds", tags=["worlds"])
async def api_list_worlds() -> dict[str, Any]:
    """List all worlds.

    Returns:
        Dict with list of world info.
    """
    try:
        from src.core.worlds import list_worlds
        return {"ok": True, "worlds": list_worlds()}
    except Exception as e:
        logger.error("Worlds list error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/worlds/{world_id}/rooms", tags=["worlds"])
async def api_list_rooms(world_id: str) -> dict[str, Any]:
    """List all rooms in a world.

    Args:
        world_id: World identifier.

    Returns:
        Dict with list of room info.
    """
    try:
        from src.core.worlds import list_rooms
        return {"ok": True, "rooms": list_rooms(world_id)}
    except Exception as e:
        logger.error("Rooms list error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/worlds/{world_id}/rooms/{room_id}", tags=["worlds"])
async def api_get_room_context(world_id: str, room_id: str) -> dict[str, Any]:
    """Get messages from a specific room.

    Args:
        world_id: World identifier.
        room_id: Room identifier.

    Returns:
        Dict with room messages.
    """
    try:
        from src.core.worlds import get_room_context
        messages = get_room_context(world_id, room_id)
        return {"ok": True, "messages": messages}
    except Exception as e:
        logger.error("Room context error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
