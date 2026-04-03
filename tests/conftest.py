"""Shared test fixtures — creates starter agent YAML files expected by tests."""

import sys
from pathlib import Path

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))


# Starter agent YAML definitions matching what the tests expect.
_STARTER_AGENTS = {
    "research_agent": {
        "name": "research_agent",
        "description": "An AI research assistant that searches the web and summarizes findings.",
        "model": "nvidia/nemotron-3-super-120b-a12b:free",
        "tools": ["search_web", "browse_url"],
        "personality": "You are a thorough research assistant. Search the web, gather relevant information, and provide clear, well-organized summaries.",
        "memory": True,
    },
    "file_helper": {
        "name": "file_helper",
        "description": "A file management assistant that reads, writes, and organizes files.",
        "model": "nvidia/nemotron-3-super-120b-a12b:free",
        "tools": ["read_file", "write_file"],
        "personality": "You are a helpful file management assistant. Help users read, create, and organize files efficiently.",
        "memory": True,
    },
    "shell_agent": {
        "name": "shell_agent",
        "description": "A system administration agent that runs shell commands safely.",
        "model": "nvidia/nemotron-3-super-120b-a12b:free",
        "tools": ["run_shell"],
        "personality": "You are a careful system administration assistant. Run shell commands to help users with system tasks. Always explain what each command does before running it.",
        "memory": True,
    },
}


@pytest.fixture(autouse=True, scope="session")
def create_starter_agents():
    """Create starter agent YAML files in ~/.pagal-os/agents/ before any test runs.

    This is a session-scoped autouse fixture — it runs once at the start of
    the test session and cleans up any agents it created afterwards.
    """
    import yaml

    agents_dir = Path.home() / ".pagal-os" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)

    created: list[Path] = []

    for agent_name, agent_data in _STARTER_AGENTS.items():
        agent_path = agents_dir / f"{agent_name}.yaml"
        if not agent_path.exists():
            agent_path.write_text(
                yaml.dump(agent_data, default_flow_style=False, sort_keys=False),
                encoding="utf-8",
            )
            created.append(agent_path)

    yield

    # Cleanup: only remove files we created (don't delete user's real agents)
    for path in created:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
