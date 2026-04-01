"""Tests for PAGAL OS agent versioning module."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core import versioning as versioning_module
from src.core.config import Settings


@pytest.fixture()
def versioning_env(tmp_path: Path):
    """Set up isolated versioning environment with temp dirs and a mock agent."""
    # Create mock agent directory and file
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    versions_dir = tmp_path / "versions"
    versions_dir.mkdir()

    agent_yaml = agents_dir / "test_agent.yaml"
    agent_data = {
        "name": "test_agent",
        "description": "A test agent",
        "model": "test-model",
        "tools": ["search_web"],
        "personality": "You are helpful.",
    }
    agent_yaml.write_text(yaml.dump(agent_data), encoding="utf-8")

    # Create a mock Settings that points to our temp dirs
    mock_settings = Settings()
    mock_settings.agents_dir = agents_dir

    with patch.object(versioning_module, "VERSIONS_DIR", versions_dir), \
         patch("src.core.versioning.get_config", return_value=mock_settings):
        yield {
            "agents_dir": agents_dir,
            "versions_dir": versions_dir,
            "settings": mock_settings,
        }


class TestSaveVersion:
    """Test saving agent versions."""

    def test_save_version(self, versioning_env: dict) -> None:
        """Should save a version and return version number 1."""
        version = versioning_module.save_version("test_agent")
        assert version == 1

        # Version file should exist
        version_file = versioning_env["versions_dir"] / "test_agent" / "v1.yaml"
        assert version_file.exists()

    def test_save_multiple_versions(self, versioning_env: dict) -> None:
        """Should increment version numbers."""
        v1 = versioning_module.save_version("test_agent")
        v2 = versioning_module.save_version("test_agent")
        v3 = versioning_module.save_version("test_agent")
        assert v1 == 1
        assert v2 == 2
        assert v3 == 3

    def test_save_version_nonexistent_agent(self, versioning_env: dict) -> None:
        """Should raise FileNotFoundError for missing agent."""
        with pytest.raises(FileNotFoundError):
            versioning_module.save_version("nonexistent_agent")


class TestListVersions:
    """Test listing agent versions."""

    def test_list_versions(self, versioning_env: dict) -> None:
        """Should list all saved versions."""
        versioning_module.save_version("test_agent")
        versioning_module.save_version("test_agent")

        versions = versioning_module.list_versions("test_agent")
        assert len(versions) == 2
        assert versions[0]["version"] == 1
        assert versions[1]["version"] == 2

    def test_list_versions_empty(self, versioning_env: dict) -> None:
        """Should return empty list when no versions saved."""
        versions = versioning_module.list_versions("test_agent")
        assert versions == []


class TestRollback:
    """Test rolling back to a previous version."""

    def test_rollback(self, versioning_env: dict) -> None:
        """Should restore agent YAML from a saved version."""
        # Save version 1
        versioning_module.save_version("test_agent")

        # Modify the agent
        agent_path = versioning_env["agents_dir"] / "test_agent.yaml"
        modified_data = {
            "name": "test_agent",
            "description": "Modified description",
            "model": "new-model",
            "tools": [],
            "personality": "Changed personality.",
        }
        agent_path.write_text(yaml.dump(modified_data), encoding="utf-8")

        # Rollback to version 1
        success = versioning_module.rollback("test_agent", 1)
        assert success is True

        # Verify the agent YAML was restored
        restored = yaml.safe_load(agent_path.read_text(encoding="utf-8"))
        assert restored["description"] == "A test agent"
        assert restored["model"] == "test-model"

    def test_rollback_nonexistent_version(self, versioning_env: dict) -> None:
        """Should return False for a nonexistent version."""
        success = versioning_module.rollback("test_agent", 999)
        assert success is False
