"""Tool-related routes: webhooks, MCP, A2A, dependencies, export, backup, migration."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from src.api.routes._models import (
    A2ACallRequest,
    A2ARegisterRequest,
    MCPConnectRequest,
    MigrateImportRequest,
    RegisterWebhookRequest,
    RestoreBackupRequest,
)

logger = logging.getLogger("pagal_os")

router = APIRouter()


# --- Webhooks ---


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


# --- MCP ---


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


# --- A2A ---


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


# --- Dependencies ---


@router.get("/api/dependencies", tags=["dependencies"])
async def api_get_dependencies() -> dict[str, Any]:
    """Get the full agent dependency graph.

    Returns:
        Dict with graph data, orphan tools, and orphan agents.
    """
    try:
        from src.core.dependencies import (
            build_dependency_graph,
            find_orphan_agents,
            find_orphan_tools,
        )

        graph = build_dependency_graph()
        return {
            "ok": True,
            "graph": graph,
            "orphan_tools": find_orphan_tools(),
            "orphan_agents": find_orphan_agents(),
        }
    except Exception as e:
        logger.error("Dependencies error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/dependencies/{agent_name}", tags=["dependencies"])
async def api_get_agent_dependencies(agent_name: str) -> dict[str, Any]:
    """Get dependencies for a specific agent.

    Args:
        agent_name: Agent name.

    Returns:
        Dict with agent dependency info.
    """
    try:
        from src.core.dependencies import get_agent_dependencies

        result = get_agent_dependencies(agent_name)
        if not result.get("ok"):
            raise HTTPException(status_code=404, detail=result.get("error", "Not found"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Agent dependencies error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/dependencies/export-dot", tags=["dependencies"])
async def api_export_dependencies_dot() -> dict[str, Any]:
    """Export the dependency graph as DOT (Graphviz) format.

    Returns:
        Dict with file path to the DOT file.
    """
    try:
        from src.core.dependencies import export_graph_dot

        path = export_graph_dot()
        return {"ok": True, "path": path}
    except Exception as e:
        logger.error("Export DOT error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/dependencies/tools", tags=["dependencies"])
async def api_get_tool_usage() -> dict[str, Any]:
    """Get which agents use which tools.

    Returns:
        Dict mapping tool names to agent lists.
    """
    try:
        from src.core.dependencies import get_tool_usage

        return {"ok": True, "tool_usage": get_tool_usage()}
    except Exception as e:
        logger.error("Tool usage error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/dependencies/models", tags=["dependencies"])
async def api_get_model_usage() -> dict[str, Any]:
    """Get which agents use which models.

    Returns:
        Dict mapping model identifiers to agent lists.
    """
    try:
        from src.core.dependencies import get_model_usage

        return {"ok": True, "model_usage": get_model_usage()}
    except Exception as e:
        logger.error("Model usage error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Export ---


@router.get("/api/export/traces", tags=["export"])
async def api_export_traces(
    agent: str | None = None,
    format: str = "json",
    days: int = 30,
) -> dict[str, Any]:
    """Export agent traces as a downloadable file.

    Args:
        agent: Optional agent name filter.
        format: Output format ('json' or 'csv').
        days: Number of days of data to export.

    Returns:
        Dict with file path.
    """
    try:
        from src.core.export import export_traces

        path = export_traces(agent_name=agent, format=format, days=days)
        return {"ok": True, "path": path}
    except Exception as e:
        logger.error("Export traces error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/export/analytics", tags=["export"])
async def api_export_analytics(
    agent: str | None = None,
    format: str = "json",
    days: int = 30,
) -> dict[str, Any]:
    """Export analytics/run data as a downloadable file.

    Args:
        agent: Optional agent name filter.
        format: Output format ('json' or 'csv').
        days: Number of days of data to export.

    Returns:
        Dict with file path.
    """
    try:
        from src.core.export import export_analytics

        path = export_analytics(agent_name=agent, format=format, days=days)
        return {"ok": True, "path": path}
    except Exception as e:
        logger.error("Export analytics error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/export/knowledge", tags=["export"])
async def api_export_knowledge(
    agent: str | None = None,
    format: str = "json",
) -> dict[str, Any]:
    """Export the knowledge graph.

    Args:
        agent: Optional agent name filter.
        format: Output format ('json' or 'csv').

    Returns:
        Dict with file path.
    """
    try:
        from src.core.export import export_knowledge

        path = export_knowledge(agent_name=agent, format=format)
        return {"ok": True, "path": path}
    except Exception as e:
        logger.error("Export knowledge error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/export/memory/{agent_name}", tags=["export"])
async def api_export_memory(
    agent_name: str,
    format: str = "json",
) -> dict[str, Any]:
    """Export an agent's cross-session memory.

    Args:
        agent_name: Agent name.
        format: Output format ('json' or 'csv').

    Returns:
        Dict with file path.
    """
    try:
        from src.core.export import export_memory

        path = export_memory(agent_name=agent_name, format=format)
        return {"ok": True, "path": path}
    except Exception as e:
        logger.error("Export memory error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/export/all", tags=["export"])
async def api_export_all(format: str = "json") -> dict[str, Any]:
    """Export all data (traces, analytics, knowledge, memory) as a zip.

    Args:
        format: Format for files inside the zip ('json' or 'csv').

    Returns:
        Dict with zip file path.
    """
    try:
        from src.core.export import export_all

        path = export_all(format=format)
        return {"ok": True, "path": path}
    except Exception as e:
        logger.error("Export all error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Backup & Restore ---


@router.post("/api/backup", tags=["backup"])
async def api_create_backup() -> dict[str, Any]:
    """Create a full system backup.

    Returns:
        Dict with backup file path.
    """
    try:
        from src.core.backup import create_backup

        path = create_backup()
        return {"ok": True, "path": path}
    except Exception as e:
        logger.error("Backup creation error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/backups", tags=["backup"])
async def api_list_backups() -> dict[str, Any]:
    """List all available backups.

    Returns:
        Dict with list of backup info.
    """
    try:
        from src.core.backup import list_backups

        return {"ok": True, "backups": list_backups()}
    except Exception as e:
        logger.error("List backups error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/restore", tags=["backup"])
async def api_restore_backup(req: RestoreBackupRequest) -> dict[str, Any]:
    """Restore a system backup from a zip file.

    Args:
        req: Request with backup file path.

    Returns:
        Dict with restored file list.
    """
    try:
        from src.core.backup import restore_backup

        result = restore_backup(req.path)
        if not result["ok"]:
            raise HTTPException(status_code=400, detail=result.get("error", "Restore failed"))
        return result
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Backup file not found")
    except Exception as e:
        logger.error("Restore backup error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/api/backup/size", tags=["backup"])
async def api_backup_size() -> dict[str, Any]:
    """Get the total size of data that would be backed up.

    Returns:
        Dict with size breakdown.
    """
    try:
        from src.core.backup import get_backup_size

        return {"ok": True, **get_backup_size()}
    except Exception as e:
        logger.error("Backup size error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


# --- Migration ---


@router.post("/api/migrate/export/{agent_name}", tags=["migration"])
async def api_migrate_export(agent_name: str) -> dict[str, Any]:
    """Export an agent as a migration package.

    Args:
        agent_name: Agent name to export.

    Returns:
        Dict with migration package path.
    """
    try:
        from src.core.migration import export_agent_full

        path = export_agent_full(agent_name)
        return {"ok": True, "path": path, "agent": agent_name}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
    except Exception as e:
        logger.error("Migration export error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/migrate/import", tags=["migration"])
async def api_migrate_import(req: MigrateImportRequest) -> dict[str, Any]:
    """Import an agent from a migration package.

    Args:
        req: Request with path to .pagal file.

    Returns:
        Dict with import result.
    """
    try:
        from src.core.migration import import_agent_full

        result = import_agent_full(req.path)
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error", "Import failed"))
        return result
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Migration package not found")
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error("Migration import error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/migrate/validate", tags=["migration"])
async def api_migrate_validate(req: MigrateImportRequest) -> dict[str, Any]:
    """Validate a migration package without importing.

    Args:
        req: Request with path to .pagal file.

    Returns:
        Dict with validation result.
    """
    try:
        from src.core.migration import validate_package

        return validate_package(req.path)
    except Exception as e:
        logger.error("Migration validate error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/api/migrate/info", tags=["migration"])
async def api_migrate_info(req: MigrateImportRequest) -> dict[str, Any]:
    """Preview a migration package contents.

    Args:
        req: Request with path to .pagal file.

    Returns:
        Dict with package info.
    """
    try:
        from src.core.migration import get_migration_info

        return get_migration_info(req.path)
    except Exception as e:
        logger.error("Migration info error: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e
