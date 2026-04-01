"""Tests for PAGAL OS agent cloning and forking module."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core import cloning as cloning_module
from src.core.config import Settings


@pytest.fixture()
def cloning_env(tmp_path: Path):
    """Set up isolated cloning environment with a test agent."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()

    # Create a source agent
    source_data = {
        "name": "source_agent",
        "description": "Original agent",
        "model": "test-model",
        "tools": ["search_web", "read_file"],
        "personality": "You are the original.",
    }
    source_path = agents_dir / "source_agent.yaml"
    source_path.write_text(yaml.dump(source_data, sort_keys=False), encoding="utf-8")

    mock_settings = Settings()
    mock_settings.agents_dir = agents_dir

    with patch("src.core.cloning.get_config", return_value=mock_settings):
        yield {
            "agents_dir": agents_dir,
            "settings": mock_settings,
        }


class TestCloneAgent:
    """Test exact cloning of agents."""

    def test_clone_agent(self, cloning_env: dict) -> None:
        """Should create an exact copy with a new name."""
        success = cloning_module.clone_agent("source_agent", "clone_agent")
        assert success is True

        # Verify clone exists
        clone_path = cloning_env["agents_dir"] / "clone_agent.yaml"
        assert clone_path.exists()

        clone_data = yaml.safe_load(clone_path.read_text(encoding="utf-8"))
        assert clone_data["name"] == "clone_agent"
        assert clone_data["forked_from"] == "source_agent"
        assert clone_data["model"] == "test-model"
        assert "search_web" in clone_data["tools"]

    def test_clone_nonexistent_source(self, cloning_env: dict) -> None:
        """Should return False when source agent doesn't exist."""
        success = cloning_module.clone_agent("nonexistent", "new_agent")
        assert success is False

    def test_clone_to_existing_name(self, cloning_env: dict) -> None:
        """Should return False when target name already exists."""
        # Clone once
        cloning_module.clone_agent("source_agent", "existing_clone")
        # Try to clone again to same name
        success = cloning_module.clone_agent("source_agent", "existing_clone")
        assert success is False


class TestForkWithChanges:
    """Test forking agents with modifications."""

    def test_fork_with_changes(self, cloning_env: dict) -> None:
        """Should create a fork with applied modifications."""
        changes = {
            "model": "new-fancy-model",
            "personality": "You are now a different agent.",
            "description": "Forked version",
        }
        success = cloning_module.fork_agent("source_agent", "forked_agent", changes)
        assert success is True

        fork_path = cloning_env["agents_dir"] / "forked_agent.yaml"
        fork_data = yaml.safe_load(fork_path.read_text(encoding="utf-8"))

        assert fork_data["model"] == "new-fancy-model"
        assert fork_data["personality"] == "You are now a different agent."
        assert fork_data["forked_from"] == "source_agent"

    def test_fork_add_tools(self, cloning_env: dict) -> None:
        """Should merge new tools into the existing list."""
        changes = {"add_tools": ["browse_url", "run_shell"]}
        success = cloning_module.fork_agent("source_agent", "tool_fork", changes)
        assert success is True

        fork_path = cloning_env["agents_dir"] / "tool_fork.yaml"
        fork_data = yaml.safe_load(fork_path.read_text(encoding="utf-8"))
        assert "browse_url" in fork_data["tools"]
        assert "search_web" in fork_data["tools"]

    def test_fork_remove_tools(self, cloning_env: dict) -> None:
        """Should remove specified tools."""
        changes = {"remove_tools": ["search_web"]}
        success = cloning_module.fork_agent("source_agent", "reduced_fork", changes)
        assert success is True

        fork_path = cloning_env["agents_dir"] / "reduced_fork.yaml"
        fork_data = yaml.safe_load(fork_path.read_text(encoding="utf-8"))
        assert "search_web" not in fork_data["tools"]
        assert "read_file" in fork_data["tools"]


class TestDiffAgents:
    """Test comparing two agents."""

    def test_diff_agents(self, cloning_env: dict) -> None:
        """Should show differences between two agents."""
        # Create a second agent with different settings
        second_data = {
            "name": "second_agent",
            "description": "Different agent",
            "model": "other-model",
            "tools": ["browse_url"],
            "personality": "You are different.",
        }
        second_path = cloning_env["agents_dir"] / "second_agent.yaml"
        second_path.write_text(yaml.dump(second_data, sort_keys=False), encoding="utf-8")

        result = cloning_module.diff_agents("source_agent", "second_agent")
        assert result["ok"] is True
        assert result["identical"] is False
        assert len(result["differences"]) > 0

        # Should have differences in model, tools, description, personality
        diff_fields = [d["field"] for d in result["differences"]]
        assert "model" in diff_fields
        assert "tools" in diff_fields

    def test_diff_identical_agents(self, cloning_env: dict) -> None:
        """Should report identical when agents are the same."""
        cloning_module.clone_agent("source_agent", "identical_clone")
        result = cloning_module.diff_agents("source_agent", "identical_clone")
        assert result["ok"] is True
        assert result["identical"] is True

    def test_diff_nonexistent_agent(self, cloning_env: dict) -> None:
        """Should return error when an agent doesn't exist."""
        result = cloning_module.diff_agents("source_agent", "ghost_agent")
        assert result["ok"] is False
        assert "not found" in result["error"]
