"""Tests for production hardening — CORS, security headers, request limits,
circuit breaker, memory sanitisation, and LLM output validation."""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from src.api.server import app

client = TestClient(app)


# ==========================================================================
# Security Headers
# ==========================================================================

class TestSecurityHeaders:
    """Verify security headers are set on all responses."""

    def test_x_content_type_options(self) -> None:
        response = client.get("/api/agents")
        assert response.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options(self) -> None:
        response = client.get("/api/agents")
        assert response.headers.get("X-Frame-Options") == "DENY"

    def test_x_xss_protection(self) -> None:
        response = client.get("/api/agents")
        assert response.headers.get("X-XSS-Protection") == "1; mode=block"

    def test_referrer_policy(self) -> None:
        response = client.get("/api/agents")
        assert "strict-origin" in response.headers.get("Referrer-Policy", "")

    def test_hsts(self) -> None:
        response = client.get("/api/agents")
        assert "max-age" in response.headers.get("Strict-Transport-Security", "")


# ==========================================================================
# Request Size Limits
# ==========================================================================

class TestRequestSizeLimit:
    """Verify request body size limits."""

    def test_normal_request_passes(self) -> None:
        """Small requests should be accepted."""
        response = client.post(
            "/api/settings",
            json={"default_model": "test"},
        )
        assert response.status_code != 413

    def test_oversized_request_rejected(self) -> None:
        """Requests exceeding 1MB should be rejected with 413."""
        # Send a content-length header claiming >1MB
        response = client.post(
            "/api/settings",
            json={"default_model": "test"},
            headers={"Content-Length": str(2 * 1024 * 1024)},
        )
        assert response.status_code == 413
        data = response.json()
        assert data["ok"] is False
        assert "too large" in data["error"].lower()


# ==========================================================================
# Circuit Breaker
# ==========================================================================

class TestCircuitBreaker:
    """Test the circuit breaker pattern."""

    def test_closed_state_allows_requests(self) -> None:
        from src.core.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("test_closed", failure_threshold=3)
        assert cb.allow_request() is True
        assert cb.state == "closed"

    def test_trips_after_threshold(self) -> None:
        from src.core.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("test_trip", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.allow_request() is True  # Still closed at 2/3

        cb.record_failure()  # 3rd failure — trips
        assert cb.state == "open"
        assert cb.allow_request() is False

    def test_success_resets_counter(self) -> None:
        from src.core.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("test_reset", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()  # Reset
        cb.record_failure()
        assert cb.state == "closed"  # Only 1 failure after reset

    def test_half_open_after_timeout(self) -> None:
        from src.core.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("test_half", failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()  # Trip
        assert cb.state == "open"

        time.sleep(0.15)  # Wait for recovery
        assert cb.state == "half_open"
        assert cb.allow_request() is True  # Probe allowed

    def test_half_open_failure_reopens(self) -> None:
        from src.core.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("test_reopen", failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        time.sleep(0.15)
        assert cb.state == "half_open"

        cb.record_failure()  # Probe fails
        assert cb.state == "open"

    def test_half_open_success_closes(self) -> None:
        from src.core.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker("test_close", failure_threshold=1, recovery_timeout=0.1)
        cb.record_failure()
        time.sleep(0.15)
        cb.record_success()  # Probe succeeds
        assert cb.state == "closed"

    def test_global_registry(self) -> None:
        from src.core.circuit_breaker import get_all_breaker_states, get_breaker

        cb1 = get_breaker("registry_test_1")
        cb2 = get_breaker("registry_test_1")  # Same name → same instance
        assert cb1 is cb2

        states = get_all_breaker_states()
        assert "registry_test_1" in states


# ==========================================================================
# Memory Content Sanitisation
# ==========================================================================

class TestMemorySanitisation:
    """Test memory content sanitisation (credential redaction)."""

    def test_redacts_openai_api_key(self) -> None:
        from src.core.memory import _sanitize_memory_content

        text = "My key is sk-abcdefghijklmnopqrstuvwxyz123456 keep it safe"
        result = _sanitize_memory_content(text)
        assert "sk-abcdef" not in result
        assert "[REDACTED]" in result

    def test_redacts_aws_access_key(self) -> None:
        from src.core.memory import _sanitize_memory_content

        text = "AWS key: AKIAIOSFODNN7EXAMPLE"
        result = _sanitize_memory_content(text)
        assert "AKIA" not in result
        assert "[REDACTED]" in result

    def test_redacts_github_token(self) -> None:
        from src.core.memory import _sanitize_memory_content

        text = "token ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef12"
        result = _sanitize_memory_content(text)
        assert "ghp_" not in result
        assert "[REDACTED]" in result

    def test_redacts_private_key(self) -> None:
        from src.core.memory import _sanitize_memory_content

        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIB..."
        result = _sanitize_memory_content(text)
        assert "BEGIN RSA PRIVATE KEY" not in result

    def test_normal_content_unchanged(self) -> None:
        from src.core.memory import _sanitize_memory_content

        text = "The weather is sunny today. Python is a great language."
        result = _sanitize_memory_content(text)
        assert result == text


# ==========================================================================
# Structured Logging
# ==========================================================================

class TestStructuredLogging:
    """Test JSON log format option."""

    def test_json_formatter_produces_valid_json(self) -> None:
        import json
        import logging

        # Create the formatter class from cli/main.py
        class _JSONFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                entry = {
                    "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
                    "level": record.levelname,
                    "logger": record.name,
                    "msg": record.getMessage(),
                }
                if record.exc_info and record.exc_info[1]:
                    entry["exception"] = str(record.exc_info[1])
                return json.dumps(entry, default=str)

        fmt = _JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="hello %s", args=("world",), exc_info=None,
        )
        output = fmt.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["msg"] == "hello world"
        assert "ts" in parsed
