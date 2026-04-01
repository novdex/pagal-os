"""Automation routes: workflows, goals, batch jobs, debugger, worlds.

Split from system.py for maintainability.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from src.api.routes._models import (
    CreateBatchRequest,
    CreateWorkflowRequest,
    ModifyContextRequest,
    RunBatchRequest,
    RunWorkflowRequest,
    SetBreakpointRequest,
    SetGoalRequest,
    StartDebugRequest,
)

logger = logging.getLogger("pagal_os")

router = APIRouter()


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
