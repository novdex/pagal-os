"""PAGAL OS Agent Dependency Graph — map relationships between agents, tools, and models.

Scans all agent YAMLs and state files to build a graph showing which
agents depend on which tools, models, other agents (via teams), and
workflows. Can export as DOT (Graphviz) format for visualization.
"""

import json
import logging
from pathlib import Path
from typing import Any

import yaml

from src.core.config import get_config

logger = logging.getLogger("pagal_os")

# Storage paths
_PAGAL_DIR = Path.home() / ".pagal-os"


def _load_all_agents() -> list[dict[str, Any]]:
    """Load all agent YAML configs from disk.

    Returns:
        List of parsed agent config dicts (with 'name' key added).
    """
    config = get_config()
    agents: list[dict[str, Any]] = []

    try:
        if not config.agents_dir.exists():
            return []

        for yaml_file in config.agents_dir.glob("*.yaml"):
            try:
                with open(yaml_file, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                data.setdefault("name", yaml_file.stem)
                agents.append(data)
            except Exception as e:
                logger.warning("Failed to load agent %s: %s", yaml_file.name, e)
    except Exception as e:
        logger.error("Failed to scan agents directory: %s", e)

    return agents


def _load_teams() -> list[dict[str, Any]]:
    """Load team definitions from the teams directory or collaboration state.

    Returns:
        List of team dicts with 'name', 'agents', and 'coordinator' keys.
    """
    teams: list[dict[str, Any]] = []
    teams_dir = _PAGAL_DIR / "teams"

    try:
        if teams_dir.exists():
            for f in teams_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    teams.append(data)
                except Exception:
                    pass
    except Exception:
        pass

    return teams


def _load_workflows() -> list[dict[str, Any]]:
    """Load workflow definitions from disk.

    Returns:
        List of workflow dicts.
    """
    workflows: list[dict[str, Any]] = []
    workflows_dir = _PAGAL_DIR / "workflows"

    try:
        if workflows_dir.exists():
            for f in workflows_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    workflows.append(data)
                except Exception:
                    pass
    except Exception:
        pass

    return workflows


def build_dependency_graph() -> dict[str, Any]:
    """Build the full dependency graph across all agents.

    Scans all agent YAMLs to determine:
    - agent -> tools used
    - agent -> model used
    - agent -> other agents (via teams)
    - agent -> workflows (if used in a workflow)

    Returns:
        Dict with 'agents', 'tools', 'models', 'teams', and 'workflows' keys,
        each containing relationship mappings.
    """
    agents = _load_all_agents()
    teams = _load_teams()
    workflows = _load_workflows()

    graph: dict[str, Any] = {
        "agents": {},
        "tools": {},
        "models": {},
        "teams": [],
        "workflows": [],
    }

    # Build agent -> tools & model mappings
    for agent in agents:
        name = agent.get("name", "unknown")
        tools = agent.get("tools", [])
        model = agent.get("model", "default")

        graph["agents"][name] = {
            "tools": tools,
            "model": model,
            "teams": [],
            "workflows": [],
        }

        # Reverse mapping: tool -> agents
        for tool in tools:
            if tool not in graph["tools"]:
                graph["tools"][tool] = []
            graph["tools"][tool].append(name)

        # Reverse mapping: model -> agents
        if model not in graph["models"]:
            graph["models"][model] = []
        graph["models"][model].append(name)

    # Map teams
    for team in teams:
        team_name = team.get("name", "unknown")
        team_agents = team.get("agents", [])
        coordinator = team.get("coordinator", "")

        graph["teams"].append({
            "name": team_name,
            "agents": team_agents,
            "coordinator": coordinator,
        })

        # Update agent -> teams
        for agent_name in team_agents:
            if agent_name in graph["agents"]:
                graph["agents"][agent_name]["teams"].append(team_name)

    # Map workflows
    for wf in workflows:
        wf_name = wf.get("name", "unknown")
        steps = wf.get("steps", [])
        wf_agents = [s.get("agent", "") for s in steps if s.get("agent")]

        graph["workflows"].append({
            "name": wf_name,
            "agents": wf_agents,
        })

        # Update agent -> workflows
        for agent_name in wf_agents:
            if agent_name in graph["agents"]:
                graph["agents"][agent_name]["workflows"].append(wf_name)

    return graph


def get_agent_dependencies(agent_name: str) -> dict[str, Any]:
    """Get all dependencies for a specific agent.

    Args:
        agent_name: Name of the agent.

    Returns:
        Dict with 'tools', 'model', 'teams', and 'workflows' keys,
        or an error dict if the agent is not found.
    """
    graph = build_dependency_graph()
    agent_data = graph["agents"].get(agent_name)

    if not agent_data:
        return {"ok": False, "error": f"Agent '{agent_name}' not found"}

    return {
        "ok": True,
        "agent_name": agent_name,
        "tools": agent_data["tools"],
        "model": agent_data["model"],
        "teams": agent_data["teams"],
        "workflows": agent_data["workflows"],
    }


def get_tool_usage() -> dict[str, list[str]]:
    """Get which agents use which tools.

    Returns:
        Dict mapping tool names to lists of agent names that use them.
        E.g. {"search_web": ["research_agent", "news_monitor"]}
    """
    graph = build_dependency_graph()
    return graph["tools"]


def get_model_usage() -> dict[str, list[str]]:
    """Get which agents use which models.

    Returns:
        Dict mapping model identifiers to lists of agent names.
    """
    graph = build_dependency_graph()
    return graph["models"]


def find_orphan_tools() -> list[str]:
    """Find tools that no agent currently uses.

    Compares registered tools against agent YAML tool lists.

    Returns:
        List of tool names not referenced by any agent.
    """
    graph = build_dependency_graph()
    used_tools = set(graph["tools"].keys())

    # Try to get all registered tools
    all_tools: set[str] = set()
    try:
        from src.tools.registry import get_tool_schemas
        schemas = get_tool_schemas()
        all_tools = {s["function"]["name"] for s in schemas if "function" in s}
    except Exception:
        pass

    return sorted(all_tools - used_tools)


def find_orphan_agents() -> list[str]:
    """Find agents not used in any team or workflow.

    Returns:
        List of agent names that are standalone (no team/workflow membership).
    """
    graph = build_dependency_graph()
    orphans: list[str] = []

    for name, data in graph["agents"].items():
        if not data["teams"] and not data["workflows"]:
            orphans.append(name)

    return sorted(orphans)


def export_graph_dot(output_path: str | None = None) -> str:
    """Export the dependency graph as DOT format (Graphviz).

    Args:
        output_path: File path to write the DOT output.
            If None, writes to ``~/.pagal-os/exports/dependencies.dot``.

    Returns:
        Absolute path to the written DOT file.
    """
    if output_path is None:
        exports_dir = _PAGAL_DIR / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(exports_dir / "dependencies.dot")

    graph = build_dependency_graph()
    lines: list[str] = [
        "digraph pagal_os {",
        '    rankdir=LR;',
        '    node [shape=box, style=filled];',
        "",
        "    // Agents (blue)",
    ]

    for name in graph["agents"]:
        lines.append(f'    "{name}" [fillcolor="#3b82f6", fontcolor="white"];')

    lines.append("")
    lines.append("    // Tools (green)")
    for tool in graph["tools"]:
        lines.append(f'    "{tool}" [shape=ellipse, fillcolor="#22c55e", fontcolor="white"];')

    lines.append("")
    lines.append("    // Models (purple)")
    for model in graph["models"]:
        safe_model = model.replace('"', '\\"')
        lines.append(f'    "{safe_model}" [shape=diamond, fillcolor="#a855f7", fontcolor="white"];')

    lines.append("")
    lines.append("    // Edges")
    for name, data in graph["agents"].items():
        for tool in data["tools"]:
            lines.append(f'    "{name}" -> "{tool}" [label="uses"];')
        safe_model = data["model"].replace('"', '\\"')
        lines.append(f'    "{name}" -> "{safe_model}" [label="model", style=dashed];')

    # Team edges
    for team in graph["teams"]:
        team_node = f"team:{team['name']}"
        lines.append(f'    "{team_node}" [shape=hexagon, fillcolor="#f59e0b", fontcolor="white"];')
        for agent_name in team["agents"]:
            lines.append(f'    "{agent_name}" -> "{team_node}" [label="member"];')

    lines.append("}")

    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
    logger.info("Exported dependency graph to %s", output_path)
    return output_path
