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
