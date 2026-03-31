"""Tests for PAGAL OS configuration loading."""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config import Settings, load_config


class TestSettings:
    """Test the Settings dataclass."""

    def test_defaults(self) -> None:
        """Settings should have sensible defaults."""
        settings = Settings()
        assert settings.version == 1
        assert settings.api_port == 8080
        assert settings.web_port == 3000
        assert "nemotron" in settings.default_model
        assert settings.max_concurrent_agents == 5
        assert settings.agent_timeout_seconds == 300

    def test_base_dir_is_path(self) -> None:
        """Base dir should be a Path object."""
        settings = Settings()
        assert isinstance(settings.base_dir, Path)


class TestLoadConfig:
    """Test the load_config function."""

    def test_load_default_config(self) -> None:
        """Should load config from project root config.yaml."""
        config = load_config()
        assert config.version == 1
        assert config.web_port == 3000
        assert isinstance(config.agents_dir, Path)

    def test_load_custom_config(self, tmp_path: Path) -> None:
        """Should load config from a custom YAML file."""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(
            "version: 2\napi_port: 9999\nweb_port: 4000\n"
        )

        config = load_config(config_path=config_file)
        assert config.version == 2
        assert config.api_port == 9999
        assert config.web_port == 4000

    def test_missing_config_uses_defaults(self, tmp_path: Path) -> None:
        """Should use defaults when config file doesn't exist."""
        config = load_config(config_path=tmp_path / "nonexistent.yaml")
        assert config.version == 1
        assert config.api_port == 8080

    def test_creates_directories(self) -> None:
        """Should create storage directories on first load."""
        config = load_config()
        assert config.agents_dir.exists()
        assert config.memory_dir.exists()
        assert config.tools_dir.exists()
        assert config.logs_dir.exists()

    def test_api_key_from_env(self) -> None:
        """Should load API key from environment."""
        os.environ["OPENROUTER_API_KEY"] = "test_key_123"
        try:
            config = load_config()
            assert config.openrouter_api_key == "test_key_123"
        finally:
            os.environ.pop("OPENROUTER_API_KEY", None)

    def test_invalid_yaml_uses_defaults(self, tmp_path: Path) -> None:
        """Should handle invalid YAML gracefully."""
        config_file = tmp_path / "bad.yaml"
        config_file.write_text(":::invalid::yaml:::")

        # Should not raise, should use defaults
        config = load_config(config_path=config_file)
        assert config.version == 1
