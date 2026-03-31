"""PAGAL OS configuration — loads settings from config.yaml and .env."""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

logger = logging.getLogger("pagal_os")


@dataclass
class Settings:
    """All runtime settings for PAGAL OS."""

    version: int = 1
    api_port: int = 8080
    web_port: int = 3000
    default_model: str = "nvidia/nemotron-3-super-120b-a12b:free"
    ollama_url: str = "http://localhost:11434"
    max_concurrent_agents: int = 5
    agent_timeout_seconds: int = 300
    storage_path: str = "~/.pagal-os"
    openrouter_api_key: str = ""

    # Derived paths (set after load)
    base_dir: Path = field(default_factory=lambda: Path.home() / ".pagal-os")
    agents_dir: Path = field(default_factory=lambda: Path.home() / ".pagal-os" / "agents")
    memory_dir: Path = field(default_factory=lambda: Path.home() / ".pagal-os" / "memory")
    tools_dir: Path = field(default_factory=lambda: Path.home() / ".pagal-os" / "tools")
    logs_dir: Path = field(default_factory=lambda: Path.home() / ".pagal-os" / "logs")


# Global settings instance
_settings: Settings | None = None


def load_config(config_path: str | Path | None = None) -> Settings:
    """Load configuration from config.yaml and .env file.

    Args:
        config_path: Path to config.yaml. Defaults to project root config.yaml.

    Returns:
        Populated Settings instance.
    """
    global _settings

    # Load .env file
    load_dotenv()

    settings = Settings()

    # Determine config file path
    if config_path is None:
        # Look in project root (where pagal.py lives)
        project_root = Path(__file__).parent.parent.parent
        config_path = project_root / "config.yaml"

    config_path = Path(config_path)

    # Load YAML config if it exists
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            settings.version = data.get("version", settings.version)
            settings.api_port = data.get("api_port", settings.api_port)
            settings.web_port = data.get("web_port", settings.web_port)
            settings.default_model = data.get("default_model", settings.default_model)
            settings.ollama_url = data.get("ollama_url", settings.ollama_url)
            settings.max_concurrent_agents = data.get("max_concurrent_agents", settings.max_concurrent_agents)
            settings.agent_timeout_seconds = data.get("agent_timeout_seconds", settings.agent_timeout_seconds)
            settings.storage_path = data.get("storage_path", settings.storage_path)

            logger.info("Loaded config from %s", config_path)
        except Exception as e:
            logger.warning("Failed to load config from %s: %s", config_path, e)
    else:
        logger.info("No config.yaml found at %s, using defaults", config_path)

    # Load API key from environment
    settings.openrouter_api_key = os.getenv("OPENROUTER_API_KEY", "")

    # Resolve storage paths
    base = Path(settings.storage_path).expanduser()
    settings.base_dir = base
    settings.agents_dir = base / "agents"
    settings.memory_dir = base / "memory"
    settings.tools_dir = base / "tools"
    settings.logs_dir = base / "logs"

    # Create directories on first run
    _ensure_directories(settings)

    _settings = settings
    return settings


def get_config() -> Settings:
    """Get the current settings, loading if needed.

    Returns:
        The global Settings instance.
    """
    global _settings
    if _settings is None:
        _settings = load_config()
    return _settings


def _ensure_directories(settings: Settings) -> None:
    """Create all required directories if they don't exist.

    Args:
        settings: Settings instance with directory paths.
    """
    dirs = [
        settings.base_dir,
        settings.agents_dir,
        settings.memory_dir,
        settings.tools_dir,
        settings.logs_dir,
    ]
    for d in dirs:
        try:
            d.mkdir(parents=True, exist_ok=True)
            logger.debug("Ensured directory: %s", d)
        except Exception as e:
            logger.error("Failed to create directory %s: %s", d, e)
