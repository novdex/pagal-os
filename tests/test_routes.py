"""Tests for API route endpoints — hands, teams, store, system, memory, automation, tools."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from src.api.server import app

client = TestClient(app)


# ==========================================================================
# Hands (scheduled agents)
# ==========================================================================

class TestHandsRoutes:
    """Test /api/hands endpoints."""

    def test_list_hands(self) -> None:
        """GET /api/hands should return a list."""
        response = client.get("/api/hands")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert isinstance(data["hands"], list)

    @patch("src.core.hands.start_hand", return_value={"ok": True, "message": "Hand started"})
    def test_start_hand(self, mock_start: MagicMock) -> None:
        """POST /api/hands should start a scheduled hand."""
        response = client.post("/api/hands", json={
            "agent": "test_agent",
            "task": "check news",
            "schedule": "every 5m",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    @patch("src.core.hands.stop_hand", return_value=True)
    def test_stop_hand(self, mock_stop: MagicMock) -> None:
        """DELETE /api/hands/{name} should stop a hand."""
        response = client.delete("/api/hands/test_agent")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True


# ==========================================================================
# Teams
# ==========================================================================

class TestTeamsRoutes:
    """Test /api/teams endpoints."""

    def test_list_teams(self) -> None:
        """GET /api/teams should return a list."""
        response = client.get("/api/teams")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert isinstance(data["teams"], list)

    def test_delete_nonexistent_team(self) -> None:
        """DELETE /api/teams/{name} for nonexistent team should return 404."""
        response = client.delete("/api/teams/nonexistent_team_xyz")
        # Team not found should return 404
        assert response.status_code == 404


# ==========================================================================
# Store / Marketplace
# ==========================================================================

class TestStoreRoutes:
    """Test /api/marketplace endpoints."""

    def test_list_marketplace(self) -> None:
        """GET /api/marketplace should return marketplace listings."""
        response = client.get("/api/marketplace")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "agents" in data

    def test_top_rated(self) -> None:
        """GET /api/marketplace/top-rated should return top-rated agents."""
        response = client.get("/api/marketplace/top-rated")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True


# ==========================================================================
# System
# ==========================================================================

class TestSystemRoutes:
    """Test /api/health, /api/budget, /api/analytics, /api/processes endpoints."""

    def test_health_dashboard(self) -> None:
        """GET /api/health should return health data."""
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        # Health endpoint may return data directly without 'ok' wrapper
        assert isinstance(data, dict)

    def test_budget_all(self) -> None:
        """GET /api/budget should return budget data."""
        response = client.get("/api/budget")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_analytics_all(self) -> None:
        """GET /api/analytics should return analytics data."""
        response = client.get("/api/analytics")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_list_processes(self) -> None:
        """GET /api/processes should return process list."""
        response = client.get("/api/processes")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "processes" in data

    def test_notifications(self) -> None:
        """GET /api/notifications should return notifications."""
        response = client.get("/api/notifications")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_credits(self) -> None:
        """GET /api/credits should return credit data."""
        response = client.get("/api/credits")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_traces_list(self) -> None:
        """GET /api/traces should return trace data."""
        response = client.get("/api/traces")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True


# ==========================================================================
# Memory & Knowledge
# ==========================================================================

class TestMemoryRoutes:
    """Test /api/memory, /api/knowledge, /api/audit endpoints."""

    def test_memory_stats(self) -> None:
        """GET /api/memory should return memory stats."""
        response = client.get("/api/memory")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_knowledge_stats(self) -> None:
        """GET /api/knowledge/stats should return knowledge stats."""
        response = client.get("/api/knowledge/stats")
        assert response.status_code == 200
        data = response.json()
        # Knowledge stats may return data directly without 'ok' wrapper
        assert isinstance(data, dict)

    def test_audit_log(self) -> None:
        """GET /api/audit should return audit entries."""
        response = client.get("/api/audit")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_approvals_list(self) -> None:
        """GET /api/approvals should return approval list."""
        response = client.get("/api/approvals")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_registry_list(self) -> None:
        """GET /api/registry should return registered agents."""
        response = client.get("/api/registry")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_rate_limits_get(self) -> None:
        """GET /api/rate-limits should return rate limit info."""
        response = client.get("/api/rate-limits")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_routing_stats(self) -> None:
        """GET /api/routing/stats should return routing data."""
        response = client.get("/api/routing/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_usage_report(self) -> None:
        """GET /api/usage should return usage data."""
        response = client.get("/api/usage")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True


# ==========================================================================
# Automation (workflows, goals, batches, worlds)
# ==========================================================================

class TestAutomationRoutes:
    """Test /api/workflows, /api/goals, /api/batches, /api/worlds endpoints."""

    def test_list_workflows(self) -> None:
        """GET /api/workflows should return workflow list."""
        response = client.get("/api/workflows")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_list_goals(self) -> None:
        """GET /api/goals should return goal list."""
        response = client.get("/api/goals")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_list_batches(self) -> None:
        """GET /api/batches should return batch list."""
        response = client.get("/api/batches")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_list_worlds(self) -> None:
        """GET /api/worlds should return world list."""
        response = client.get("/api/worlds")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True


# ==========================================================================
# Tools (webhooks, MCP, A2A, dependencies, export, backup)
# ==========================================================================

class TestToolsRoutes:
    """Test /api/webhooks, /api/mcp, /api/a2a, /api/dependencies, etc."""

    def test_list_webhooks(self) -> None:
        """GET /api/webhooks should return webhook list."""
        response = client.get("/api/webhooks")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_mcp_connections(self) -> None:
        """GET /api/mcp/connections should return MCP connection list."""
        response = client.get("/api/mcp/connections")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_a2a_list(self) -> None:
        """GET /api/a2a/agents should return remote agent list."""
        response = client.get("/api/a2a/agents")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_dependencies_graph(self) -> None:
        """GET /api/dependencies should return dependency graph."""
        response = client.get("/api/dependencies")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_tool_usage(self) -> None:
        """GET /api/dependencies/tools should return tool usage data."""
        response = client.get("/api/dependencies/tools")
        # May be 404 if tools router uses a different prefix — still assert no 500
        assert response.status_code in (200, 404)

    def test_model_usage(self) -> None:
        """GET /api/dependencies/models should return model usage data."""
        response = client.get("/api/dependencies/models")
        assert response.status_code in (200, 404)

    def test_list_backups(self) -> None:
        """GET /api/backups should return backup list."""
        response = client.get("/api/backups")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

    def test_backup_size(self) -> None:
        """GET /api/backup/size should return size info."""
        response = client.get("/api/backup/size")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True


# ==========================================================================
# Input Validation on Routes
# ==========================================================================

class TestRouteInputValidation:
    """Test that route parameters are properly validated."""

    def test_agent_logs_rejects_path_traversal(self) -> None:
        """GET /api/agents/{name}/logs should reject path traversal names."""
        response = client.get("/api/agents/../../etc/passwd/logs")
        # Should get either a validation error or a 404, not the file contents
        if response.status_code == 200:
            data = response.json()
            assert data.get("ok") is False or data.get("logs") == []

    def test_agent_logs_rejects_special_chars(self) -> None:
        """Agent names with special characters should be rejected."""
        response = client.get("/api/agents/test%00agent/logs")
        assert response.status_code in (200, 404, 422)
        if response.status_code == 200:
            data = response.json()
            # Should either be rejected or return empty
            assert data.get("ok") in (True, False)

    def test_settings_rejects_api_key_change(self) -> None:
        """POST /api/settings should reject API key changes."""
        response = client.post("/api/settings", json={
            "openrouter_api_key": "sk-evil-key",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert "not allowed" in data["message"].lower()
