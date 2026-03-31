"""Tests for PAGAL OS agent runtime."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.runtime import (
    AgentConfig,
    AgentResult,
    delete_agent,
    get_agent_status,
    list_agents,
    load_agent,
    run_agent,
    stop_agent,
)


class TestAgentConfig:
    """Test the AgentConfig dataclass."""

    def test_create_config(self) -> None:
        """Should create an AgentConfig with all fields."""
        config = AgentConfig(
            name="test_agent",
            description="A test agent",
            model="test-model",
            tools=["search_web"],
            personality="You are a test agent.",
        )
        assert config.name == "test_agent"
        assert config.memory is True  # default
        assert config.schedule is None  # default

    def test_default_values(self) -> None:
        """Should have sensible defaults."""
        config = AgentConfig(
            name="minimal",
            description="",
            model="test",
        )
        assert config.tools == []
        assert config.personality == "You are a helpful AI assistant."


class TestAgentResult:
    """Test the AgentResult dataclass."""

    def test_success_result(self) -> None:
        """Should create a success result."""
        result = AgentResult(ok=True, output="Done!", tools_used=["search_web"], duration_seconds=1.5)
        assert result.ok is True
        assert result.error == ""

    def test_error_result(self) -> None:
        """Should create an error result."""
        result = AgentResult(ok=False, output="", error="Something broke")
        assert result.ok is False
        assert result.error == "Something broke"


class TestLoadAgent:
    """Test agent loading from YAML."""

    def test_load_existing_agent(self) -> None:
        """Should load a starter agent successfully."""
        # Starter agents were created in ~/.pagal-os/agents/
        agent = load_agent("research_agent")
        assert agent.name == "research_agent"
        assert "search_web" in agent.tools
        assert len(agent.personality) > 0

    def test_load_nonexistent_agent(self) -> None:
        """Should raise FileNotFoundError for missing agent."""
        with pytest.raises(FileNotFoundError):
            load_agent("this_agent_does_not_exist_xyz")


class TestListAgents:
    """Test agent listing."""

    def test_list_returns_agents(self) -> None:
        """Should return at least the starter agents."""
        agents = list_agents()
        assert isinstance(agents, list)
        names = [a["name"] for a in agents]
        assert "research_agent" in names
        assert "file_helper" in names
        assert "shell_agent" in names

    def test_agent_dict_has_required_fields(self) -> None:
        """Each agent dict should have name, description, status."""
        agents = list_agents()
        for agent in agents:
            assert "name" in agent
            assert "description" in agent
            assert "status" in agent


class TestRunAgent:
    """Test agent execution with mocked LLM."""

    @patch("src.core.runtime.call_llm")
    def test_run_agent_simple(self, mock_llm: MagicMock) -> None:
        """Should run agent and return result when LLM gives direct response."""
        mock_llm.return_value = {
            "ok": True,
            "content": "Here is the answer.",
            "tool_calls": None,
            "error": "",
        }

        agent = AgentConfig(
            name="test",
            description="test",
            model="test-model",
            tools=[],
            personality="You are helpful.",
        )

        result = run_agent(agent, "What is 2+2?")
        assert result.ok is True
        assert result.output == "Here is the answer."
        assert result.tools_used == []

    @patch("src.core.runtime.execute_tool")
    @patch("src.core.runtime.call_llm")
    def test_run_agent_with_tool_call(self, mock_llm: MagicMock, mock_exec: MagicMock) -> None:
        """Should handle tool calls in the agent loop."""
        # First call returns tool call, second call returns final answer
        mock_llm.side_effect = [
            {
                "ok": True,
                "content": "",
                "tool_calls": [{
                    "id": "call_1",
                    "function": {
                        "name": "search_web",
                        "arguments": '{"query": "AI news"}',
                    },
                }],
                "error": "",
            },
            {
                "ok": True,
                "content": "Based on my search, here are the results.",
                "tool_calls": None,
                "error": "",
            },
        ]

        mock_exec.return_value = {"ok": True, "result": [{"title": "AI News", "url": "http://example.com"}]}

        # Need to import tools so schemas are available
        import src.tools  # noqa: F401

        agent = AgentConfig(
            name="test",
            description="test",
            model="test-model",
            tools=["search_web"],
            personality="You are a researcher.",
        )

        result = run_agent(agent, "Find AI news")
        assert result.ok is True
        assert "search" in result.output.lower() or "results" in result.output.lower()
        assert "search_web" in result.tools_used

    @patch("src.core.runtime.call_llm")
    def test_run_agent_llm_error(self, mock_llm: MagicMock) -> None:
        """Should handle LLM errors gracefully."""
        mock_llm.return_value = {
            "ok": False,
            "content": "",
            "tool_calls": None,
            "error": "API key invalid",
        }

        agent = AgentConfig(
            name="test",
            description="test",
            model="test-model",
        )

        result = run_agent(agent, "test task")
        assert result.ok is False
        assert "API key" in result.error


class TestAgentStatus:
    """Test agent status management."""

    def test_idle_status(self) -> None:
        """Should return idle for non-running agents."""
        status = get_agent_status("research_agent")
        assert status["status"] == "idle"

    def test_stop_non_running(self) -> None:
        """Should return False when stopping a non-running agent."""
        result = stop_agent("not_running_agent")
        assert result is False
