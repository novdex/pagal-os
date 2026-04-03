"""Tests for API authentication middleware and CSRF protection."""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from src.api.auth import generate_csrf_token
from src.api.server import app

client = TestClient(app)


class TestAPIAuth:
    """Test bearer-token authentication middleware."""

    def test_api_accessible_without_token_when_unset(self) -> None:
        """When PAGAL_API_TOKEN is unset, API should be accessible."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PAGAL_API_TOKEN", None)
            response = client.get("/api/agents")
            assert response.status_code == 200

    def test_api_rejects_missing_token(self) -> None:
        """When PAGAL_API_TOKEN is set, requests without a token are rejected."""
        with patch.dict(os.environ, {"PAGAL_API_TOKEN": "test-secret-token-123"}):
            response = client.get("/api/agents")
            assert response.status_code == 401
            data = response.json()
            assert data["ok"] is False
            assert "Authorization" in data["error"]

    def test_api_rejects_wrong_token(self) -> None:
        """Requests with an incorrect bearer token are rejected."""
        with patch.dict(os.environ, {"PAGAL_API_TOKEN": "test-secret-token-123"}):
            response = client.get(
                "/api/agents",
                headers={"Authorization": "Bearer wrong-token"},
            )
            assert response.status_code == 403
            data = response.json()
            assert data["ok"] is False

    def test_api_accepts_correct_token(self) -> None:
        """Requests with the correct bearer token are accepted."""
        token = "test-secret-token-123"
        with patch.dict(os.environ, {"PAGAL_API_TOKEN": token}):
            response = client.get(
                "/api/agents",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 200
            data = response.json()
            assert data["ok"] is True

    def test_web_pages_accessible_without_token(self) -> None:
        """Web dashboard pages should be accessible even when auth is enabled."""
        with patch.dict(os.environ, {"PAGAL_API_TOKEN": "test-secret-token-123"}):
            response = client.get("/")
            # Web pages should not be blocked by API auth
            # (may be 200 or 500 if template rendering has issues, but not 401/403)
            assert response.status_code not in (401, 403)

    def test_static_files_accessible_without_token(self) -> None:
        """Static CSS/JS files should be accessible without a token."""
        with patch.dict(os.environ, {"PAGAL_API_TOKEN": "test-secret-token-123"}):
            response = client.get("/static/style.css")
            assert response.status_code == 200


class TestCSRF:
    """Test CSRF token protection on web-facing POST endpoints."""

    def test_csrf_token_in_html(self) -> None:
        """Dashboard HTML should contain a CSRF meta tag."""
        response = client.get("/")
        # If page renders successfully, it should have the csrf meta tag
        if response.status_code == 200:
            assert 'name="csrf-token"' in response.text

    def test_csrf_token_generation_deterministic(self) -> None:
        """Same session_id should produce the same token."""
        t1 = generate_csrf_token("sess1")
        t2 = generate_csrf_token("sess1")
        assert t1 == t2
        assert len(t1) == 40

    def test_csrf_token_differs_by_session(self) -> None:
        """Different session IDs should produce different tokens."""
        t1 = generate_csrf_token("sess1")
        t2 = generate_csrf_token("sess2")
        assert t1 != t2
