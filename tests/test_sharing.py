"""Tests for PAGAL OS agent sharing module."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core import sharing as sharing_module
from src.core.config import Settings


@pytest.fixture()
def sharing_env(tmp_path: Path):
    """Set up isolated sharing environment."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    shared_dir = tmp_path / "shared"
    shared_dir.mkdir()
    codes_file = tmp_path / "share_codes.json"

    # Create a test agent
    agent_data = {
        "name": "share_test",
        "description": "An agent for sharing tests",
        "model": "test-model",
        "tools": ["search_web"],
        "personality": "You are shareable.",
    }
    agent_path = agents_dir / "share_test.yaml"
    agent_path.write_text(yaml.dump(agent_data, sort_keys=False), encoding="utf-8")

    mock_settings = Settings()
    mock_settings.agents_dir = agents_dir

    with patch.object(sharing_module, "SHARED_DIR", shared_dir), \
         patch.object(sharing_module, "SHARE_CODES_FILE", codes_file), \
         patch("src.core.sharing.get_config", return_value=mock_settings):
        yield {
            "agents_dir": agents_dir,
            "shared_dir": shared_dir,
            "codes_file": codes_file,
            "settings": mock_settings,
        }


class TestExportImportRoundTrip:
    """Test exporting and re-importing agents."""

    def test_export_import_round_trip(self, sharing_env: dict) -> None:
        """Should export an agent to JSON and import it back identically."""
        # Export
        export_path = sharing_module.export_agent("share_test")
        assert Path(export_path).exists()

        # Read exported data
        exported = json.loads(Path(export_path).read_text(encoding="utf-8"))
        assert exported["agent"]["name"] == "share_test"
        assert "yaml" in exported["agent"]
        assert "share_code" in exported

        # Delete the original agent
        original_path = sharing_env["agents_dir"] / "share_test.yaml"
        original_path.unlink()
        assert not original_path.exists()

        # Import
        imported_name = sharing_module.import_agent(export_path)
        assert imported_name == "share_test"

        # Verify the agent was recreated
        assert original_path.exists()
        reimported = yaml.safe_load(original_path.read_text(encoding="utf-8"))
        assert reimported["name"] == "share_test"
        assert reimported["model"] == "test-model"

    def test_export_nonexistent_agent(self, sharing_env: dict) -> None:
        """Should raise FileNotFoundError for missing agent."""
        with pytest.raises(FileNotFoundError):
            sharing_module.export_agent("nonexistent_agent")

    def test_import_invalid_file(self, sharing_env: dict) -> None:
        """Should raise error for invalid share file format."""
        bad_file = sharing_env["shared_dir"] / "bad.json"
        bad_file.write_text('{"invalid": true}', encoding="utf-8")

        with pytest.raises(ValueError, match="Invalid share file"):
            sharing_module.import_agent(str(bad_file))

    def test_import_nonexistent_file(self, sharing_env: dict) -> None:
        """Should raise FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            sharing_module.import_agent("/nonexistent/share.json")


class TestShareCode:
    """Test share code generation and lookup."""

    def test_share_code_generation(self, sharing_env: dict) -> None:
        """Should generate an 8-character alphanumeric code."""
        code = sharing_module.generate_share_code("share_test")
        assert len(code) == 8
        assert code.isalnum()

    def test_share_code_idempotent(self, sharing_env: dict) -> None:
        """Should return the same code for the same agent on subsequent calls."""
        code1 = sharing_module.generate_share_code("share_test")
        code2 = sharing_module.generate_share_code("share_test")
        assert code1 == code2

    def test_share_code_persisted(self, sharing_env: dict) -> None:
        """Share codes should be saved to disk."""
        code = sharing_module.generate_share_code("share_test")
        assert sharing_env["codes_file"].exists()

        codes = json.loads(sharing_env["codes_file"].read_text(encoding="utf-8"))
        assert code in codes
        assert codes[code]["agent_name"] == "share_test"
