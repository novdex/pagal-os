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


class RateAgentRequest(BaseModel):
    """Request body for rating a marketplace agent."""

    rating: int
    review: str = ""


class CloneAgentRequest(BaseModel):
    """Request body for cloning an agent."""

    new_name: str


class ForkAgentRequest(BaseModel):
    """Request body for forking an agent."""

    new_name: str
    changes: dict[str, Any] = {}


class RegisterWebhookRequest(BaseModel):
    """Request body for registering a webhook."""

    agent_name: str
    event_type: str = "http"
    config: dict[str, Any] = {}


class ImportAgentRequest(BaseModel):
    """Request body for importing a shared agent."""

    file_path: str


class RollbackRequest(BaseModel):
    """Request body for rolling back an agent version."""

    version: int


class StartHandRequest(BaseModel):
    """Request body for starting a scheduled hand."""

    agent: str
    schedule: str
    task: str


class CreateTeamRequest(BaseModel):
    """Request body for creating a team."""

    name: str
    agents: list[str]
    coordinator: str
    goal: str = ""


class RunTeamRequest(BaseModel):
    """Request body for running a team task."""

    task: str


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


# --- Hands API Endpoints ---


@router.post("/api/hands", tags=["hands"])
async def api_start_hand(req: StartHandRequest) -> dict[str, Any]:
    """Start a scheduled autonomous hand.

    Args:
        req: Request with agent name, schedule, and task.

    Returns:
        Dict with status info.
    """
    try:
        from src.core.hands import start_hand
        result = start_hand(req.agent, req.schedule, req.task)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to start hand: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/hands", tags=["hands"])
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


@router.delete("/api/hands/{name}", tags=["hands"])
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


# --- Teams API Endpoints ---


@router.post("/api/teams", tags=["teams"])
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


@router.get("/api/teams", tags=["teams"])
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


@router.post("/api/teams/{name}/run", tags=["teams"])
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


@router.delete("/api/teams/{name}", tags=["teams"])
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


# --- Usage API Endpoint ---


# --- Marketplace API Endpoints ---


@router.get("/api/marketplace", tags=["marketplace"])
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


@router.post("/api/marketplace/install/{agent_id}", tags=["marketplace"])
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


# --- Knowledge API Endpoints ---


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


# --- Audit API Endpoint ---


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


# --- Processes API Endpoints ---


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


# --- Memory API Endpoints ---


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


# --- MCP API Endpoints ---


@router.get("/api/mcp/connections", tags=["mcp"])
async def api_mcp_connections() -> dict[str, Any]:
    """List all MCP server connections.

    Returns:
        Dict with list of MCP connection info.
    """
    try:
        from src.core.mcp import list_mcp_connections
        return {"ok": True, "connections": list_mcp_connections()}
    except Exception as e:
        logger.error("MCP connections error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


class MCPConnectRequest(BaseModel):
    """Request body for connecting to an MCP server."""

    name: str
    command: str
    args: list[str] = []
    env: dict[str, str] = {}


@router.post("/api/mcp/connect", tags=["mcp"])
async def api_mcp_connect(req: MCPConnectRequest) -> dict[str, Any]:
    """Connect to an external MCP server.

    Args:
        req: Connection details.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.mcp import connect_mcp_server
        ok = connect_mcp_server(req.name, req.command, req.args, req.env)
        if ok:
            return {"ok": True, "message": f"Connected to MCP server '{req.name}'"}
        raise HTTPException(status_code=500, detail=f"Failed to connect to '{req.name}'")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("MCP connect error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/api/mcp/connections/{name}", tags=["mcp"])
async def api_mcp_disconnect(name: str) -> dict[str, Any]:
    """Disconnect an MCP server.

    Args:
        name: MCP server name.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.mcp import disconnect_mcp_server
        disconnect_mcp_server(name)
        return {"ok": True, "message": f"Disconnected MCP server '{name}'"}
    except Exception as e:
        logger.error("MCP disconnect error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- A2A API Endpoints ---


class A2ARegisterRequest(BaseModel):
    """Request body for registering a remote agent."""

    agent_name: str
    url: str


class A2ACallRequest(BaseModel):
    """Request body for calling a remote agent."""

    agent_name: str
    task: str


@router.get("/api/a2a/agents", tags=["a2a"])
async def api_a2a_list() -> dict[str, Any]:
    """List all registered remote agents.

    Returns:
        Dict with list of remote agent endpoints.
    """
    try:
        from src.core.a2a import list_remote_agents
        return {"ok": True, "agents": list_remote_agents()}
    except Exception as e:
        logger.error("A2A list error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/a2a/register", tags=["a2a"])
async def api_a2a_register(req: A2ARegisterRequest) -> dict[str, Any]:
    """Register a remote agent endpoint.

    Args:
        req: Registration details.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.a2a import register_agent_endpoint
        ok = register_agent_endpoint(req.agent_name, req.url)
        return {"ok": ok, "message": f"Registered '{req.agent_name}' at {req.url}"}
    except Exception as e:
        logger.error("A2A register error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/a2a/call", tags=["a2a"])
async def api_a2a_call(req: A2ACallRequest) -> dict[str, Any]:
    """Call a remote agent.

    Args:
        req: Call details with agent name and task.

    Returns:
        Dict with remote agent's response.
    """
    try:
        from src.core.a2a import call_remote_agent
        result = call_remote_agent(req.agent_name, req.task)
        return result
    except Exception as e:
        logger.error("A2A call error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Worlds API Endpoints ---


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


# --- Marketplace Rating & Review Endpoints ---


@router.post("/api/marketplace/{agent_id}/rate", tags=["marketplace"])
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

        if not 1 <= req.rating <= 5:
            raise HTTPException(status_code=400, detail="Rating must be 1-5")
        if rate_agent(agent_id, req.rating, req.review):
            return {"ok": True, "message": f"Agent '{agent_id}' rated {req.rating} stars"}
        raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Rate agent error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/marketplace/{agent_id}/reviews", tags=["marketplace"])
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


@router.get("/api/marketplace/top-rated", tags=["marketplace"])
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


# --- Approval Gate Endpoints ---


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


# --- Cloning & Forking Endpoints ---


@router.post("/api/agents/{name}/clone", tags=["agents"])
async def api_clone_agent(name: str, req: CloneAgentRequest) -> dict[str, Any]:
    """Clone an agent to create an exact copy.

    Args:
        name: Source agent name.
        req: Request with new_name.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.cloning import clone_agent

        if clone_agent(name, req.new_name):
            return {"ok": True, "message": f"Agent '{name}' cloned to '{req.new_name}'"}
        raise HTTPException(status_code=400, detail=f"Failed to clone '{name}'")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Clone error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/agents/{name}/fork", tags=["agents"])
async def api_fork_agent(name: str, req: ForkAgentRequest) -> dict[str, Any]:
    """Fork an agent with modifications.

    Args:
        name: Source agent name.
        req: Request with new_name and changes dict.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.cloning import fork_agent

        if fork_agent(name, req.new_name, req.changes):
            return {"ok": True, "message": f"Agent '{name}' forked to '{req.new_name}'"}
        raise HTTPException(status_code=400, detail=f"Failed to fork '{name}'")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Fork error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Analytics Endpoints ---


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


# --- Webhook Endpoints ---


@router.post("/webhooks/{webhook_id}", tags=["webhooks"])
async def api_receive_webhook(webhook_id: str, request: Request) -> dict[str, Any]:
    """Receive an external webhook and trigger the associated agent.

    Args:
        webhook_id: The registered webhook ID.
        request: The incoming HTTP request with POST payload.

    Returns:
        Dict with agent execution result.
    """
    try:
        from src.core.webhooks import handle_webhook

        try:
            payload = await request.json()
        except Exception:
            payload = {}

        result = handle_webhook(webhook_id, payload)
        if not result.get("ok"):
            status_code = 404 if "not found" in result.get("error", "").lower() else 500
            raise HTTPException(status_code=status_code, detail=result.get("error"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Webhook receive error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/webhooks", tags=["webhooks"])
async def api_list_webhooks() -> dict[str, Any]:
    """List all registered webhooks.

    Returns:
        Dict with list of webhook entries.
    """
    try:
        from src.core.webhooks import list_webhooks

        return {"ok": True, "webhooks": list_webhooks()}
    except Exception as e:
        logger.error("List webhooks error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/webhooks", tags=["webhooks"])
async def api_register_webhook(req: RegisterWebhookRequest) -> dict[str, Any]:
    """Register a new webhook trigger.

    Args:
        req: Request with agent_name, event_type, and optional config.

    Returns:
        Dict with webhook URL.
    """
    try:
        from src.core.webhooks import register_webhook

        url = register_webhook(req.agent_name, req.event_type, req.config)
        if url:
            return {"ok": True, "url": url}
        raise HTTPException(status_code=500, detail="Failed to register webhook")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Register webhook error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.delete("/api/webhooks/{webhook_id}", tags=["webhooks"])
async def api_delete_webhook(webhook_id: str) -> dict[str, Any]:
    """Delete a registered webhook.

    Args:
        webhook_id: The webhook to remove.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.webhooks import delete_webhook

        if delete_webhook(webhook_id):
            return {"ok": True, "message": f"Webhook '{webhook_id}' deleted"}
        raise HTTPException(status_code=404, detail=f"Webhook '{webhook_id}' not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Delete webhook error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Versioning API Endpoints ---


@router.get("/api/agents/{name}/versions", tags=["versioning"])
async def api_list_versions(name: str) -> dict[str, Any]:
    """List all saved versions for an agent.

    Args:
        name: Agent name.

    Returns:
        Dict with list of version info.
    """
    try:
        from src.core.versioning import list_versions
        versions = list_versions(name)
        return {"ok": True, "agent": name, "versions": versions}
    except Exception as e:
        logger.error("List versions error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/agents/{name}/rollback/{version}", tags=["versioning"])
async def api_rollback_agent(name: str, version: int) -> dict[str, Any]:
    """Rollback an agent to a previous version.

    Args:
        name: Agent name.
        version: Version number to restore.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.versioning import rollback
        if rollback(name, version):
            return {"ok": True, "message": f"Agent '{name}' rolled back to v{version}"}
        raise HTTPException(
            status_code=404,
            detail=f"Version {version} not found for agent '{name}'",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Rollback error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/agents/{name}/versions/{version}", tags=["versioning"])
async def api_get_version(name: str, version: int) -> dict[str, Any]:
    """Get the content of a specific agent version.

    Args:
        name: Agent name.
        version: Version number.

    Returns:
        Dict with version content.
    """
    try:
        from src.core.versioning import get_version
        result = get_version(name, version)
        if not result.get("ok"):
            raise HTTPException(status_code=404, detail=result.get("error", "Not found"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Get version error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/agents/{name}/versions/diff", tags=["versioning"])
async def api_diff_versions(name: str, v1: int = 1, v2: int = 2) -> dict[str, Any]:
    """Show differences between two versions of an agent.

    Args:
        name: Agent name.
        v1: First version number.
        v2: Second version number.

    Returns:
        Dict with differences.
    """
    try:
        from src.core.versioning import diff_versions
        return diff_versions(name, v1, v2)
    except Exception as e:
        logger.error("Diff versions error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Sharing API Endpoints ---


@router.post("/api/agents/{name}/share", tags=["sharing"])
async def api_share_agent(name: str) -> dict[str, Any]:
    """Export an agent and generate a share code.

    Args:
        name: Agent name.

    Returns:
        Dict with share code and file path.
    """
    try:
        from src.core.sharing import export_agent
        import json as _json

        file_path = export_agent(name)
        data = _json.loads(Path(file_path).read_text(encoding="utf-8"))
        return {
            "ok": True,
            "share_code": data.get("share_code", ""),
            "file_path": file_path,
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    except Exception as e:
        logger.error("Share agent error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/agents/import", tags=["sharing"])
async def api_import_agent(req: ImportAgentRequest) -> dict[str, Any]:
    """Import an agent from a shared JSON file.

    Args:
        req: Request with file_path.

    Returns:
        Dict with imported agent name.
    """
    try:
        from src.core.sharing import import_agent
        name = import_agent(req.file_path)
        return {"ok": True, "name": name, "message": f"Agent '{name}' imported"}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Share file not found")
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error("Import agent error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Encryption API Endpoints ---


@router.post("/api/agents/{name}/encrypt", tags=["encryption"])
async def api_encrypt_agent(name: str) -> dict[str, Any]:
    """Encrypt an agent's memory and config files.

    Args:
        name: Agent name.

    Returns:
        Dict with success status.
    """
    try:
        from src.core.encryption import encrypt_agent_memory
        if encrypt_agent_memory(name):
            return {"ok": True, "message": f"Agent '{name}' encrypted"}
        return {"ok": False, "message": f"No files found to encrypt for '{name}'"}
    except Exception as e:
        logger.error("Encrypt agent error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/agents/{name}/decrypt", tags=["encryption"])
async def api_decrypt_agent(name: str) -> dict[str, Any]:
    """Decrypt and return an agent's encrypted files.

    Args:
        name: Agent name.

    Returns:
        Dict with decrypted file contents.
    """
    try:
        from src.core.encryption import decrypt_agent_memory
        results = decrypt_agent_memory(name)
        return {"ok": True, "files": results}
    except Exception as e:
        logger.error("Decrypt agent error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Traces API Endpoints ---


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


@router.get("/store", response_class=HTMLResponse, tags=["web"])
async def page_store(request: Request) -> HTMLResponse:
    """Serve the agent store/marketplace page.

    Args:
        request: FastAPI request object.

    Returns:
        Rendered HTML store page.
    """
    return templates.TemplateResponse(request, "store.html")


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


@router.get("/builder", response_class=HTMLResponse, tags=["web"])
async def page_builder(request: Request) -> HTMLResponse:
    """Serve the visual drag-and-drop agent builder page.

    Args:
        request: FastAPI request object.

    Returns:
        Rendered HTML builder page.
    """
    return templates.TemplateResponse(request, "builder.html")


@router.get("/analytics", response_class=HTMLResponse, tags=["web"])
async def page_analytics(request: Request) -> HTMLResponse:
    """Serve the analytics page.

    Args:
        request: FastAPI request object.

    Returns:
        Rendered HTML analytics page.
    """
    return templates.TemplateResponse(request, "analytics.html")


@router.get("/traces", response_class=HTMLResponse, tags=["web"])
async def page_traces(request: Request) -> HTMLResponse:
    """Serve the traces page.

    Args:
        request: FastAPI request object.

    Returns:
        Rendered HTML traces page.
    """
    return templates.TemplateResponse(request, "traces.html")


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
