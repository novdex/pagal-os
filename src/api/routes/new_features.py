"""API routes for new features — RAG, templates, WhatsApp, MCP catalog,
webhook bridge, plugins, i18n, and voice API."""

import logging
from typing import Any

from fastapi import APIRouter, Query, Request, UploadFile, File
from fastapi.responses import JSONResponse, PlainTextResponse

logger = logging.getLogger("pagal_os")

router = APIRouter()


# ==========================================================================
# RAG — Document Q&A
# ==========================================================================

@router.get("/api/rag/documents", tags=["rag"])
async def api_rag_list_docs(agent_name: str = "_global") -> dict[str, Any]:
    """List all ingested documents."""
    from src.core.rag import list_documents
    return list_documents(agent_name)


@router.post("/api/rag/ingest", tags=["rag"])
async def api_rag_ingest(req: dict[str, Any]) -> dict[str, Any]:
    """Ingest a document by file path."""
    from src.core.rag import ingest_document
    return ingest_document(req.get("filepath", ""), agent_name=req.get("agent_name", "_global"))


@router.post("/api/rag/ingest-text", tags=["rag"])
async def api_rag_ingest_text(req: dict[str, Any]) -> dict[str, Any]:
    """Ingest raw text content."""
    from src.core.rag import ingest_text
    return ingest_text(
        req.get("content", ""),
        title=req.get("title", "pasted_text"),
        agent_name=req.get("agent_name", "_global"),
    )


@router.post("/api/rag/query", tags=["rag"])
async def api_rag_query(req: dict[str, Any]) -> dict[str, Any]:
    """Query documents for relevant content."""
    from src.core.rag import query_documents
    return query_documents(
        req.get("query", ""),
        agent_name=req.get("agent_name", "_global"),
        top_k=req.get("top_k", 5),
    )


@router.delete("/api/rag/documents/{doc_id}", tags=["rag"])
async def api_rag_delete_doc(doc_id: int) -> dict[str, Any]:
    """Delete a document and its chunks."""
    from src.core.rag import delete_document
    return delete_document(doc_id)


# ==========================================================================
# Agent Templates
# ==========================================================================

@router.get("/api/templates", tags=["templates"])
async def api_list_templates(category: str | None = None) -> dict[str, Any]:
    """List available agent templates."""
    from src.core.templates import get_categories, list_templates
    return {
        "ok": True,
        "templates": list_templates(category),
        "categories": get_categories(),
    }


@router.post("/api/templates/{template_id}/install", tags=["templates"])
async def api_install_template(template_id: str) -> dict[str, Any]:
    """Install a template as a real agent."""
    from src.core.templates import install_template
    return install_template(template_id)


# ==========================================================================
# WhatsApp Channel
# ==========================================================================

@router.get("/api/whatsapp/webhook", tags=["whatsapp"])
async def api_whatsapp_verify(
    request: Request,
) -> PlainTextResponse:
    """Verify WhatsApp webhook (Meta sends GET with challenge)."""
    from src.channels.whatsapp import verify_webhook
    mode = request.query_params.get("hub.mode", "")
    token = request.query_params.get("hub.verify_token", "")
    challenge = request.query_params.get("hub.challenge", "")
    result = verify_webhook(mode, token, challenge)
    if result:
        return PlainTextResponse(content=result)
    return PlainTextResponse(content="Verification failed", status_code=403)


@router.post("/api/whatsapp/webhook", tags=["whatsapp"])
async def api_whatsapp_incoming(request: Request) -> dict[str, Any]:
    """Handle incoming WhatsApp messages."""
    from src.channels.whatsapp import handle_webhook
    payload = await request.json()
    handle_webhook(payload)
    return {"ok": True}


# ==========================================================================
# MCP Server Catalog
# ==========================================================================

@router.get("/api/mcp/catalog", tags=["mcp"])
async def api_mcp_catalog(category: str | None = None) -> dict[str, Any]:
    """List available MCP servers from the catalog."""
    from src.core.mcp_catalog import get_catalog_categories, list_catalog
    return {
        "ok": True,
        "servers": list_catalog(category),
        "categories": get_catalog_categories(),
    }


@router.post("/api/mcp/catalog/{server_id}/install", tags=["mcp"])
async def api_mcp_install_from_catalog(server_id: str) -> dict[str, Any]:
    """Connect to an MCP server from the catalog."""
    from src.core.mcp_catalog import install_from_catalog
    return install_from_catalog(server_id)


# ==========================================================================
# Webhook Bridge (Zapier/n8n)
# ==========================================================================

@router.post("/api/webhook-bridge/run", tags=["webhook-bridge"])
async def api_webhook_bridge_run(request: Request) -> dict[str, Any]:
    """Inbound webhook: run an agent from Zapier/n8n/Make.

    Expected JSON: {"agent": "agent_name", "task": "do something"}
    """
    from src.core.webhook_bridge import handle_bridge_request
    payload = await request.json()
    return handle_bridge_request(payload)


# ==========================================================================
# Plugins
# ==========================================================================

@router.get("/api/plugins", tags=["plugins"])
async def api_list_plugins() -> dict[str, Any]:
    """List all installed plugins."""
    from src.core.plugins import list_plugins
    return {"ok": True, "plugins": list_plugins()}


@router.post("/api/plugins/load", tags=["plugins"])
async def api_load_plugins() -> dict[str, Any]:
    """Load/reload all plugins from the plugins directory."""
    from src.core.plugins import load_plugins
    results = load_plugins()
    return {"ok": True, "results": results}


@router.post("/api/plugins/create", tags=["plugins"])
async def api_create_plugin(req: dict[str, Any]) -> dict[str, Any]:
    """Create a new plugin from template."""
    from src.core.plugins import create_plugin_template
    return create_plugin_template(req.get("name", ""))


# ==========================================================================
# i18n (Multi-Language)
# ==========================================================================

@router.get("/api/i18n/languages", tags=["i18n"])
async def api_supported_languages() -> dict[str, Any]:
    """List supported languages."""
    from src.core.i18n import get_language, get_supported_languages
    return {
        "ok": True,
        "current": get_language(),
        "languages": get_supported_languages(),
    }


@router.get("/api/i18n/translations", tags=["i18n"])
async def api_translations(lang: str | None = None) -> dict[str, Any]:
    """Get all translations for a language."""
    from src.core.i18n import get_all_translations
    return {"ok": True, "translations": get_all_translations(lang)}


# ==========================================================================
# Voice API (Voice-First Interaction)
# ==========================================================================

@router.post("/api/voice/process", tags=["voice"])
async def api_voice_process(
    agent_name: str = Query(default="research_assistant"),
    audio: UploadFile = File(...),
) -> dict[str, Any]:
    """Process a voice message: transcribe -> run agent -> return text + audio.

    Accepts audio file upload, transcribes it, runs the agent, and returns
    both the text response and a base64-encoded audio response.
    """
    try:
        from src.channels.voice import process_voice_message
        import base64

        audio_bytes = await audio.read()
        text_response, audio_response = process_voice_message(audio_bytes, agent_name)

        result: dict[str, Any] = {
            "ok": True,
            "text": text_response,
        }
        if audio_response:
            result["audio_base64"] = base64.b64encode(audio_response).decode("ascii")

        return result

    except Exception as e:
        logger.error("Voice processing failed: %s", e)
        return {"ok": False, "error": str(e)}


@router.post("/api/voice/transcribe", tags=["voice"])
async def api_voice_transcribe(audio: UploadFile = File(...)) -> dict[str, Any]:
    """Transcribe audio to text (STT only)."""
    try:
        from src.channels.voice import transcribe_audio

        audio_bytes = await audio.read()
        text = transcribe_audio(audio_bytes)
        return {"ok": True, "text": text}

    except Exception as e:
        return {"ok": False, "error": str(e)}


# ==========================================================================
# Smart Memory (Mem0-style facts)
# ==========================================================================

@router.get("/api/facts", tags=["smart-memory"])
async def api_get_facts(agent_name: str = "_global", category: str | None = None) -> dict[str, Any]:
    """Get all stored facts for an agent."""
    from src.core.smart_memory import get_facts
    facts = get_facts(agent_name, category=category)
    return {"ok": True, "facts": facts}


@router.post("/api/facts", tags=["smart-memory"])
async def api_add_fact(req: dict[str, Any]) -> dict[str, Any]:
    """Add a fact to smart memory."""
    from src.core.smart_memory import add_fact
    return add_fact(
        fact=req.get("fact", ""),
        agent_name=req.get("agent_name", "_global"),
        category=req.get("category", "general"),
        confidence=req.get("confidence", 1.0),
        expires_at=req.get("expires_at"),
    )


@router.delete("/api/facts/{fact_id}", tags=["smart-memory"])
async def api_delete_fact(fact_id: int) -> dict[str, Any]:
    """Delete a fact."""
    from src.core.smart_memory import forget_fact
    return forget_fact(fact_id)


@router.post("/api/facts/extract", tags=["smart-memory"])
async def api_extract_facts(req: dict[str, Any]) -> dict[str, Any]:
    """Extract facts from text automatically."""
    from src.core.smart_memory import extract_facts_from_text
    facts = extract_facts_from_text(req.get("text", ""), agent_name=req.get("agent_name", "_global"))
    return {"ok": True, "extracted": facts}


# ==========================================================================
# Payments & Marketplace Monetization
# ==========================================================================

@router.get("/api/pricing/{agent_name}", tags=["payments"])
async def api_get_pricing(agent_name: str) -> dict[str, Any]:
    """Get pricing for an agent."""
    from src.core.payments import get_agent_pricing
    return {"ok": True, **get_agent_pricing(agent_name)}


@router.post("/api/pricing", tags=["payments"])
async def api_set_pricing(req: dict[str, Any]) -> dict[str, Any]:
    """Set pricing for an agent."""
    from src.core.payments import set_agent_pricing
    return set_agent_pricing(
        agent_name=req.get("agent_name", ""),
        pricing_model=req.get("pricing_model", "free"),
        price_per_use=req.get("price_per_use", 0.0),
        monthly_price=req.get("monthly_price", 0.0),
        free_runs_per_month=req.get("free_runs_per_month", 10),
    )


@router.get("/api/revenue", tags=["payments"])
async def api_revenue() -> dict[str, Any]:
    """Get revenue report."""
    from src.core.payments import get_revenue_report
    return get_revenue_report()


# ==========================================================================
# Multi-Step Planning
# ==========================================================================

@router.post("/api/plan", tags=["planner"])
async def api_create_plan(req: dict[str, Any]) -> dict[str, Any]:
    """Create a multi-step execution plan for a task."""
    from src.core.planner import create_plan
    plan = create_plan(req.get("task", ""), req.get("tools", []))
    return {
        "ok": True,
        "task": plan.task,
        "steps": [{"index": s.index, "description": s.description, "tool": s.tool} for s in plan.steps],
    }


@router.post("/api/plan/execute", tags=["planner"])
async def api_execute_plan(req: dict[str, Any]) -> dict[str, Any]:
    """Create and execute a plan with self-reflection."""
    from src.core.planner import create_plan, execute_plan
    plan = create_plan(req.get("task", ""), req.get("tools", []))
    return execute_plan(plan, agent_name=req.get("agent_name", ""))


# ==========================================================================
# Escalation / Human Handoff
# ==========================================================================

@router.get("/api/escalations", tags=["escalation"])
async def api_get_escalations(agent_name: str | None = None) -> dict[str, Any]:
    """Get pending escalations."""
    from src.core.escalation import get_pending_escalations
    return {"ok": True, "escalations": get_pending_escalations(agent_name)}


@router.post("/api/escalations/{escalation_id}/resolve", tags=["escalation"])
async def api_resolve_escalation(escalation_id: str, req: dict[str, Any]) -> dict[str, Any]:
    """Resolve an escalation."""
    from src.core.escalation import resolve_escalation
    return resolve_escalation(
        escalation_id=escalation_id,
        decision=req.get("decision", "approved"),
        response=req.get("response", ""),
        responder=req.get("responder", "operator"),
    )


# ==========================================================================
# Agent Cloning with Learning Transfer
# ==========================================================================

@router.post("/api/agents/{source}/clone-with-learning", tags=["cloning"])
async def api_clone_with_learning(source: str, req: dict[str, Any]) -> dict[str, Any]:
    """Clone an agent with full knowledge transfer."""
    from src.core.learning_transfer import clone_with_learning
    return clone_with_learning(
        source_name=source,
        new_name=req.get("new_name", ""),
        transfer_memory=req.get("transfer_memory", True),
        transfer_facts=req.get("transfer_facts", True),
        transfer_knowledge=req.get("transfer_knowledge", True),
        personality_override=req.get("personality", ""),
    )


@router.get("/api/agents/{name}/lineage", tags=["cloning"])
async def api_agent_lineage(name: str) -> dict[str, Any]:
    """Get the fork lineage of an agent."""
    from src.core.learning_transfer import get_agent_lineage
    return get_agent_lineage(name)


# ==========================================================================
# Scheduled Reports
# ==========================================================================

@router.get("/api/reports", tags=["reports"])
async def api_list_reports() -> dict[str, Any]:
    """List all scheduled reports."""
    from src.core.scheduled_reports import list_reports
    return {"ok": True, "reports": list_reports()}


@router.post("/api/reports", tags=["reports"])
async def api_create_report(req: dict[str, Any]) -> dict[str, Any]:
    """Create a scheduled report."""
    from src.core.scheduled_reports import create_scheduled_report
    return create_scheduled_report(
        name=req.get("name", ""),
        agent_name=req.get("agent_name", ""),
        task=req.get("task", ""),
        schedule=req.get("schedule", ""),
        delivery=req.get("delivery"),
    )


@router.post("/api/reports/{report_id}/run", tags=["reports"])
async def api_run_report(report_id: str) -> dict[str, Any]:
    """Manually run a report."""
    from src.core.scheduled_reports import run_report
    return run_report(report_id)


@router.delete("/api/reports/{report_id}", tags=["reports"])
async def api_delete_report(report_id: str) -> dict[str, Any]:
    """Delete a scheduled report."""
    from src.core.scheduled_reports import delete_report
    return delete_report(report_id)


# ==========================================================================
# Natural Language Workflow Builder
# ==========================================================================

@router.post("/api/workflows/build-from-text", tags=["nl-workflows"])
async def api_build_workflow(req: dict[str, Any]) -> dict[str, Any]:
    """Build a complete workflow from a natural language description."""
    from src.core.nl_workflows import build_workflow
    return build_workflow(req.get("description", ""))


@router.post("/api/workflows/parse", tags=["nl-workflows"])
async def api_parse_workflow(req: dict[str, Any]) -> dict[str, Any]:
    """Parse a description into workflow components (without creating anything)."""
    from src.core.nl_workflows import parse_workflow_description
    return parse_workflow_description(req.get("description", ""))


@router.get("/api/workflows/suggestions", tags=["nl-workflows"])
async def api_workflow_suggestions() -> dict[str, Any]:
    """Get example workflow descriptions users can try."""
    from src.core.nl_workflows import list_workflow_suggestions
    return {"ok": True, "suggestions": list_workflow_suggestions()}

