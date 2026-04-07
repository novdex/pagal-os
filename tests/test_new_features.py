"""Tests for new features — RAG, templates, MCP catalog, webhook bridge,
i18n, plugins, email, WhatsApp, and new API routes."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from src.api.server import app

client = TestClient(app)


# ==========================================================================
# RAG — Document Q&A
# ==========================================================================

class TestRAG:
    """Test RAG document ingestion and querying."""

    def test_ingest_text(self) -> None:
        from src.core.rag import ingest_text
        # Use unique content to avoid dedup
        import time
        content = f"The capital of France is Paris. Test timestamp: {time.time()}"
        result = ingest_text(content, title="test_facts")
        assert result["ok"] is True
        assert result["chunks"] > 0

    def test_query_documents(self) -> None:
        from src.core.rag import ingest_text, query_documents
        ingest_text("Python was created by Guido van Rossum in 1991.", title="python_facts")
        result = query_documents("Who created Python?")
        assert result["ok"] is True
        assert len(result["results"]) > 0
        assert "Guido" in result["results"][0]["content"]

    def test_list_documents(self) -> None:
        from src.core.rag import list_documents
        result = list_documents()
        assert result["ok"] is True
        assert isinstance(result["documents"], list)

    def test_ingest_empty_rejected(self) -> None:
        from src.core.rag import ingest_text
        result = ingest_text("", title="empty")
        assert result["ok"] is False

    def test_api_rag_query(self) -> None:
        response = client.post("/api/rag/query", json={"query": "test"})
        assert response.status_code == 200

    def test_api_rag_list(self) -> None:
        response = client.get("/api/rag/documents")
        assert response.status_code == 200


# ==========================================================================
# Agent Templates
# ==========================================================================

class TestTemplates:
    """Test pre-built agent templates."""

    def test_list_templates(self) -> None:
        from src.core.templates import list_templates
        templates = list_templates()
        assert len(templates) >= 25
        names = [t["name"] for t in templates]
        assert "Research Assistant" in names
        assert "Email Writer" in names
        assert "Document Q&A" in names

    def test_list_by_category(self) -> None:
        from src.core.templates import list_templates
        research = list_templates(category="Research")
        assert all(t["category"] == "Research" for t in research)
        assert len(research) >= 3

    def test_get_template(self) -> None:
        from src.core.templates import get_template
        t = get_template("research_assistant")
        assert t is not None
        assert t["config"]["name"] == "research_assistant"
        assert "search_web" in t["config"]["tools"]

    def test_install_template(self) -> None:
        from src.core.templates import install_template
        result = install_template("email_writer")
        assert result["ok"] is True
        assert result["agent_name"] == "email_writer"

    def test_get_categories(self) -> None:
        from src.core.templates import get_categories
        cats = get_categories()
        assert "Research" in cats
        assert "Writing" in cats
        assert "Productivity" in cats

    def test_api_list_templates(self) -> None:
        response = client.get("/api/templates")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert len(data["templates"]) >= 25

    def test_api_install_template(self) -> None:
        response = client.post("/api/templates/daily_briefing/install")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True


# ==========================================================================
# MCP Server Catalog
# ==========================================================================

class TestMCPCatalog:
    """Test MCP server catalog."""

    def test_list_catalog(self) -> None:
        from src.core.mcp_catalog import list_catalog
        servers = list_catalog()
        assert len(servers) >= 10
        names = [s["name"] for s in servers]
        assert "GitHub" in names
        assert "Slack" in names

    def test_filter_by_category(self) -> None:
        from src.core.mcp_catalog import list_catalog
        dev_servers = list_catalog(category="Development")
        assert all(s["category"] == "Development" for s in dev_servers)

    def test_get_entry(self) -> None:
        from src.core.mcp_catalog import get_catalog_entry
        entry = get_catalog_entry("github")
        assert entry is not None
        assert entry["command"] == "npx"

    def test_api_mcp_catalog(self) -> None:
        response = client.get("/api/mcp/catalog")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert len(data["servers"]) >= 10


# ==========================================================================
# Webhook Bridge
# ==========================================================================

class TestWebhookBridge:
    """Test Zapier/n8n webhook bridge."""

    def test_bridge_missing_fields(self) -> None:
        from src.core.webhook_bridge import handle_bridge_request
        result = handle_bridge_request({})
        assert result["ok"] is False
        assert "Missing" in result["error"]

    def test_bridge_agent_not_found(self) -> None:
        from src.core.webhook_bridge import handle_bridge_request
        result = handle_bridge_request({"agent": "nonexistent_xyz", "task": "test"})
        assert result["ok"] is False

    def test_api_webhook_bridge(self) -> None:
        response = client.post("/api/webhook-bridge/run", json={
            "agent": "research_assistant",
            "task": "test",
        })
        # Will fail due to no API key, but endpoint should respond
        assert response.status_code == 200


# ==========================================================================
# i18n (Multi-Language)
# ==========================================================================

class TestI18n:
    """Test internationalization."""

    def test_translate_english(self) -> None:
        from src.core.i18n import t
        assert t("dashboard", "en") == "Dashboard"
        assert t("create_agent", "en") == "Create Agent"

    def test_translate_hindi(self) -> None:
        from src.core.i18n import t
        assert t("dashboard", "hi") == "डैशबोर्ड"

    def test_translate_spanish(self) -> None:
        from src.core.i18n import t
        assert t("dashboard", "es") == "Panel"

    def test_translate_chinese(self) -> None:
        from src.core.i18n import t
        assert t("dashboard", "zh") == "仪表板"

    def test_translate_french(self) -> None:
        from src.core.i18n import t
        assert t("dashboard", "fr") == "Tableau de bord"

    def test_fallback_to_english(self) -> None:
        from src.core.i18n import t
        # Unknown key falls back to English, then to key itself
        assert t("nonexistent_key", "hi") == "nonexistent_key"

    def test_supported_languages(self) -> None:
        from src.core.i18n import get_supported_languages
        langs = get_supported_languages()
        codes = [l["code"] for l in langs]
        assert "en" in codes
        assert "hi" in codes
        assert "es" in codes

    def test_api_languages(self) -> None:
        response = client.get("/api/i18n/languages")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert len(data["languages"]) >= 5

    def test_api_translations(self) -> None:
        response = client.get("/api/i18n/translations?lang=es")
        assert response.status_code == 200
        data = response.json()
        assert data["translations"]["dashboard"] == "Panel"


# ==========================================================================
# Plugins
# ==========================================================================

class TestPlugins:
    """Test the plugin system."""

    def test_list_plugins(self) -> None:
        from src.core.plugins import list_plugins
        plugins = list_plugins()
        assert isinstance(plugins, list)

    def test_create_plugin_template(self) -> None:
        from src.core.plugins import create_plugin_template, get_plugins_dir
        result = create_plugin_template("_test_plugin")
        assert result["ok"] is True
        assert Path(result["path"]).exists()
        # Cleanup
        Path(result["path"]).unlink(missing_ok=True)

    def test_create_duplicate_rejected(self) -> None:
        from src.core.plugins import create_plugin_template
        create_plugin_template("_test_dup")
        result = create_plugin_template("_test_dup")
        assert result["ok"] is False
        # Cleanup
        from src.core.plugins import get_plugins_dir
        (get_plugins_dir() / "_test_dup.py").unlink(missing_ok=True)

    def test_api_plugins(self) -> None:
        response = client.get("/api/plugins")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True


# ==========================================================================
# Docker
# ==========================================================================

class TestDocker:
    """Test Docker configuration files exist."""

    def test_dockerfile_exists(self) -> None:
        dockerfile = Path(__file__).parent.parent / "Dockerfile"
        assert dockerfile.exists()
        content = dockerfile.read_text()
        assert "python:3.12" in content
        assert "pagal.py" in content

    def test_docker_compose_exists(self) -> None:
        compose = Path(__file__).parent.parent / "docker-compose.yml"
        assert compose.exists()
        content = compose.read_text()
        assert "pagal-os" in content
        assert "3000:3000" in content

    def test_dockerignore_exists(self) -> None:
        dockerignore = Path(__file__).parent.parent / ".dockerignore"
        assert dockerignore.exists()


# ==========================================================================
# PWA
# ==========================================================================

class TestPWA:
    """Test PWA configuration."""

    def test_manifest_exists(self) -> None:
        manifest = Path(__file__).parent.parent / "src" / "web" / "static" / "manifest.json"
        assert manifest.exists()
        import json
        data = json.loads(manifest.read_text())
        assert data["name"] == "PAGAL OS"
        assert data["display"] == "standalone"

    def test_service_worker_exists(self) -> None:
        sw = Path(__file__).parent.parent / "src" / "web" / "static" / "sw.js"
        assert sw.exists()
        content = sw.read_text()
        assert "CACHE_NAME" in content

    def test_manifest_link_in_html(self) -> None:
        response = client.get("/")
        if response.status_code == 200:
            assert "manifest.json" in response.text
