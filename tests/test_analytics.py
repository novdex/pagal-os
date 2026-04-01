"""Tests for PAGAL OS agent analytics module."""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core import analytics as analytics_module


@pytest.fixture(autouse=True)
def isolate_analytics_db(tmp_path: Path):
    """Redirect the analytics DB to a temp directory for each test."""
    test_dir = tmp_path / ".pagal-os"
    test_dir.mkdir()
    test_db = test_dir / "pagal.db"
    with patch.object(analytics_module, "_PAGAL_DIR", test_dir), \
         patch.object(analytics_module, "_DB_PATH", test_db):
        yield


class TestRecordRun:
    """Test recording agent runs."""

    def test_record_run(self) -> None:
        """Should record a run without error."""
        # Should not raise
        analytics_module.record_run(
            agent_name="test_agent",
            task="Find news",
            success=True,
            duration=2.5,
            tokens=500,
            tools=3,
            cost=0.001,
        )

        # Verify by querying
        stats = analytics_module.get_agent_analytics("test_agent", days=1)
        assert stats["total_runs"] == 1
        assert stats["success_rate"] == 100.0

    def test_record_failed_run(self) -> None:
        """Should record a failed run with error message."""
        analytics_module.record_run(
            agent_name="fail_agent",
            task="Broken task",
            success=False,
            duration=0.5,
            tokens=100,
            tools=0,
            cost=0.0001,
            error="API timeout",
        )

        stats = analytics_module.get_agent_analytics("fail_agent", days=1)
        assert stats["total_runs"] == 1
        assert stats["success_rate"] == 0.0


class TestGetAgentAnalytics:
    """Test per-agent analytics queries."""

    def test_get_agent_analytics(self) -> None:
        """Should compute correct aggregate statistics."""
        for i in range(5):
            analytics_module.record_run(
                agent_name="analytics_test",
                task=f"Task {i}",
                success=i < 4,  # 4 successes, 1 failure
                duration=float(i + 1),
                tokens=100 * (i + 1),
                tools=i,
                cost=0.001 * (i + 1),
            )

        stats = analytics_module.get_agent_analytics("analytics_test", days=1)
        assert stats["total_runs"] == 5
        assert stats["success_rate"] == 80.0  # 4/5
        assert stats["total_tokens"] == 1500  # 100+200+300+400+500
        assert stats["total_cost"] > 0

    def test_get_analytics_nonexistent_agent(self) -> None:
        """Should return zero stats for an agent with no runs."""
        stats = analytics_module.get_agent_analytics("ghost_agent", days=30)
        assert stats["total_runs"] == 0
        assert stats["success_rate"] == 0.0


class TestGetAllAnalytics:
    """Test system-wide analytics."""

    def test_get_all_analytics(self) -> None:
        """Should aggregate across all agents."""
        analytics_module.record_run("agent_1", "task1", True, 1.0, 100, 1, 0.001)
        analytics_module.record_run("agent_2", "task2", True, 2.0, 200, 2, 0.002)
        analytics_module.record_run("agent_2", "task3", False, 0.5, 50, 0, 0.0005)

        all_stats = analytics_module.get_all_analytics(days=1)
        assert all_stats["total_runs"] == 3
        assert len(all_stats["agents"]) == 2
        # Agent 2 has more runs so should be first
        agent_names = [a["agent_name"] for a in all_stats["agents"]]
        assert "agent_1" in agent_names
        assert "agent_2" in agent_names

    def test_get_all_analytics_empty(self) -> None:
        """Should return zero stats when no runs recorded."""
        all_stats = analytics_module.get_all_analytics(days=30)
        assert all_stats["total_runs"] == 0
        assert all_stats["agents"] == []
