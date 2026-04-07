"""Tests for power features — WebSocket, code interpreter, smart memory,
payments, planner, escalation, vision, learning transfer, reports, NL workflows."""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from src.api.server import app

client = TestClient(app)


class TestCodeInterpreter:
    def test_basic_execution(self) -> None:
        from src.tools.code_interpreter import run_python
        result = run_python("print(2 + 2)")
        assert result["ok"] is True
        assert "4" in result["stdout"]

    def test_math_calculation(self) -> None:
        from src.tools.code_interpreter import run_python
        result = run_python("import math; print(f'{math.pi:.4f}')")
        assert result["ok"] is True
        assert "3.141" in result["stdout"]

    def test_data_analysis(self) -> None:
        from src.tools.code_interpreter import run_python
        code = """
data = [10, 20, 30, 40, 50]
avg = sum(data) / len(data)
print(f"Average: {avg}")
"""
        result = run_python(code)
        assert result["ok"] is True
        assert "30" in result["stdout"]

    def test_dangerous_code_blocked(self) -> None:
        from src.tools.code_interpreter import run_python
        result = run_python("import subprocess; subprocess.run(['rm', '-rf', '/'])")
        assert result["ok"] is False
        assert "Blocked" in result.get("error", "")

    def test_timeout(self) -> None:
        from src.tools.code_interpreter import run_python
        result = run_python("import time; time.sleep(60)", timeout=2)
        assert result["ok"] is False
        assert "timed out" in result.get("error", "").lower()

    def test_syntax_error(self) -> None:
        from src.tools.code_interpreter import run_python
        result = run_python("def broken(")
        assert result["ok"] is False


class TestSmartMemory:
    def test_add_and_get_facts(self) -> None:
        from src.core.smart_memory import add_fact, get_facts
        r = add_fact("User likes dark mode", agent_name="_test", category="preference")
        assert r["ok"] is True
        facts = get_facts("_test")
        assert any("dark mode" in f["fact"] for f in facts)

    def test_fact_categories(self) -> None:
        from src.core.smart_memory import add_fact, get_facts
        add_fact("User is vegetarian", agent_name="_test", category="health")
        facts = get_facts("_test", category="health")
        assert any("vegetarian" in f["fact"] for f in facts)

    def test_extract_facts(self) -> None:
        from src.core.smart_memory import extract_facts_from_text
        text = "I am a software engineer. I like Python. I work at Google."
        facts = extract_facts_from_text(text, agent_name="_test_extract")
        assert len(facts) > 0

    def test_build_context(self) -> None:
        from src.core.smart_memory import add_fact, build_fact_context
        add_fact("User speaks Hindi", agent_name="_test_ctx", category="personal")
        ctx = build_fact_context("_test_ctx")
        assert "Hindi" in ctx

    def test_forget_fact(self) -> None:
        from src.core.smart_memory import add_fact, forget_fact
        r = add_fact("Temp fact", agent_name="_test_del")
        forget_fact(r["id"])

    def test_api_facts(self) -> None:
        response = client.get("/api/facts")
        assert response.status_code == 200
        assert response.json()["ok"] is True


class TestPayments:
    def test_set_and_get_pricing(self) -> None:
        from src.core.payments import set_agent_pricing, get_agent_pricing
        set_agent_pricing("test_paid_agent", pricing_model="pay_per_use", price_per_use=0.05)
        pricing = get_agent_pricing("test_paid_agent")
        assert pricing["pricing_model"] == "pay_per_use"
        assert pricing["price_per_use"] == 0.05

    def test_usage_quota(self) -> None:
        from src.core.payments import check_usage_quota, set_agent_pricing
        set_agent_pricing("quota_test", pricing_model="pay_per_use", free_runs_per_month=3)
        quota = check_usage_quota("quota_test")
        assert quota["allowed"] is True

    def test_free_agent_always_allowed(self) -> None:
        from src.core.payments import check_usage_quota
        quota = check_usage_quota("nonexistent_agent")
        assert quota["allowed"] is True

    def test_api_pricing(self) -> None:
        response = client.get("/api/pricing/test_agent")
        assert response.status_code == 200

    def test_api_revenue(self) -> None:
        response = client.get("/api/revenue")
        assert response.status_code == 200


class TestPlanner:
    def test_plan_structure(self) -> None:
        from src.core.planner import PlanStep, ExecutionPlan
        plan = ExecutionPlan(task="test", steps=[
            PlanStep(index=0, description="Step 1"),
            PlanStep(index=1, description="Step 2"),
        ])
        assert len(plan.steps) == 2
        assert plan.status == "planning"

    def test_api_plan(self) -> None:
        response = client.post("/api/plan", json={"task": "find AI news", "tools": ["search_web"]})
        assert response.status_code == 200


class TestEscalation:
    def test_create_escalation(self) -> None:
        from src.core.escalation import create_escalation, get_pending_escalations
        r = create_escalation("test_agent", "sensitive task", "low confidence", confidence=0.2)
        assert r["ok"] is True
        pending = get_pending_escalations()
        assert len(pending) > 0

    def test_resolve_escalation(self) -> None:
        from src.core.escalation import create_escalation, resolve_escalation
        r = create_escalation("test_agent2", "task", "test", confidence=0.1)
        resolved = resolve_escalation(r["id"], "approved", response="Go ahead")
        assert resolved["ok"] is True
        assert resolved["status"] == "approved"

    def test_should_escalate(self) -> None:
        from src.core.escalation import should_escalate
        assert should_escalate("agent", "task", confidence=0.2) is True
        assert should_escalate("agent", "task", confidence=0.9) is False
        assert should_escalate("agent", "task", confidence=0.5, action_type="financial") is True

    def test_api_escalations(self) -> None:
        response = client.get("/api/escalations")
        assert response.status_code == 200


class TestLearningTransfer:
    def test_clone_creates_agent(self) -> None:
        from src.core.learning_transfer import clone_with_learning
        # Install a template first
        from src.core.templates import install_template
        install_template("blog_writer")
        r = clone_with_learning("blog_writer", "_test_clone_lt")
        assert r["ok"] is True
        assert r["agent_name"] == "_test_clone_lt"
        # Cleanup
        config_dir = Path.home() / ".pagal-os" / "agents"
        (config_dir / "_test_clone_lt.yaml").unlink(missing_ok=True)

    def test_lineage(self) -> None:
        from src.core.learning_transfer import get_agent_lineage
        r = get_agent_lineage("research_assistant")
        assert r["ok"] is True

    def test_api_lineage(self) -> None:
        response = client.get("/api/agents/research_assistant/lineage")
        assert response.status_code == 200


class TestScheduledReports:
    def test_create_report(self) -> None:
        from src.core.scheduled_reports import create_scheduled_report, list_reports
        r = create_scheduled_report(
            name="Test Report", agent_name="research_assistant",
            task="summarize AI news", schedule="daily at 09:00",
        )
        assert r["ok"] is True
        reports = list_reports()
        assert any(rp["name"] == "Test Report" for rp in reports)

    def test_api_reports(self) -> None:
        response = client.get("/api/reports")
        assert response.status_code == 200


class TestNLWorkflows:
    def test_suggestions(self) -> None:
        from src.core.nl_workflows import list_workflow_suggestions
        suggestions = list_workflow_suggestions()
        assert len(suggestions) >= 5

    def test_api_suggestions(self) -> None:
        response = client.get("/api/workflows/suggestions")
        assert response.status_code == 200
        assert len(response.json()["suggestions"]) >= 5

    def test_api_parse(self) -> None:
        response = client.post("/api/workflows/parse", json={"description": "test workflow"})
        assert response.status_code == 200


class TestWebSocket:
    def test_ws_endpoint_exists(self) -> None:
        """WebSocket endpoint should accept connections."""
        with client.websocket_connect("/ws/agent/run") as ws:
            ws.send_json({"agent": "", "task": ""})
            data = ws.receive_json()
            assert data["event"] == "error"


class TestNewAPIRoutes:
    """Verify all new API routes respond."""

    @pytest.mark.parametrize("path", [
        "/api/facts",
        "/api/escalations",
        "/api/reports",
        "/api/revenue",
        "/api/workflows/suggestions",
    ])
    def test_get_routes(self, path: str) -> None:
        response = client.get(path)
        assert response.status_code == 200
        assert response.json()["ok"] is True
