"""Tests for PAGAL OS API endpoints."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from src.api.server import app

client = TestClient(app)


class TestAPIAgents:
    """Test agent API endpoints."""

    def test_list_agents(self) -> None:
        """GET /api/agents should return a list of agents."""
        response = client.get("/api/agents")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert isinstance(data["agents"], list)

    def test_list_agents_has_starter_agents(self) -> None:
        """Should include the starter agents."""
        response = client.get("/api/agents")
        data = response.json()
        names = [a["name"] for a in data["agents"]]
        assert "research_agent" in names

    def test_agent_status(self) -> None:
        """GET /api/agents/{name}/status should return status."""
        response = client.get("/api/agents/research_agent/status")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "status" in data

    @patch("src.api.routes.run_in_sandbox")
    @patch("src.api.routes.load_agent")
    def test_run_agent(self, mock_load: MagicMock, mock_sandbox: MagicMock) -> None:
        """POST /api/agents/{name}/run should execute the agent."""
        from src.core.runtime import AgentConfig, AgentResult

        mock_load.return_value = AgentConfig(
            name="research_agent",
            description="test",
            model="test",
            tools=[],
        )
        mock_sandbox.return_value = AgentResult(
            ok=True,
            output="Test result",
            tools_used=["search_web"],
            duration_seconds=1.0,
        )

        response = client.post(
            "/api/agents/research_agent/run",
            json={"task": "find AI news"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["output"] == "Test result"

    def test_run_nonexistent_agent(self) -> None:
        """Should return 404 for nonexistent agent."""
        response = client.post(
            "/api/agents/nonexistent_xyz_agent/run",
            json={"task": "test"},
        )
        assert response.status_code == 404

    def test_delete_nonexistent_agent(self) -> None:
        """Should return 404 when deleting nonexistent agent."""
        response = client.delete("/api/agents/nonexistent_xyz_agent")
        assert response.status_code == 404

    def test_agent_logs_empty(self) -> None:
        """Should return empty logs for agent with no logs."""
        response = client.get("/api/agents/research_agent/logs")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True


class TestAPISettings:
    """Test settings API endpoints."""

    def test_update_settings(self) -> None:
        """POST /api/settings should update settings."""
        response = client.post(
            "/api/settings",
            json={"default_model": "test-model"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True


class TestWebPages:
    """Test web page routes return HTML."""

    def test_dashboard_page(self) -> None:
        """GET / should return HTML dashboard."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "PAGAL OS" in response.text

    def test_create_page(self) -> None:
        """GET /create should return HTML create page."""
        response = client.get("/create")
        assert response.status_code == 200
        assert "Create Agent" in response.text

    def test_logs_page(self) -> None:
        """GET /logs should return HTML logs page."""
        response = client.get("/logs")
        assert response.status_code == 200
        assert "Logs" in response.text

    def test_settings_page(self) -> None:
        """GET /settings should return HTML settings page."""
        response = client.get("/settings")
        assert response.status_code == 200
        assert "Settings" in response.text

    def test_static_css(self) -> None:
        """GET /static/style.css should return CSS."""
        response = client.get("/static/style.css")
        assert response.status_code == 200

    def test_static_js(self) -> None:
        """GET /static/app.js should return JS."""
        response = client.get("/static/app.js")
        assert response.status_code == 200
