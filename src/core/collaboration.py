"""Multi-agent collaboration -- agents work together as a team.

A team has a coordinator agent that receives tasks, breaks them into
subtasks, delegates each subtask to the best agent, collects results,
and synthesizes a final report.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import yaml

from src.core.config import get_config

logger = logging.getLogger("pagal_os")


def _get_teams_dir() -> Path:
    """Get the directory for team configurations.

    Returns:
        Path to ~/.pagal-os/teams/.
    """
    config = get_config()
    teams_dir = config.base_dir / "teams"
    teams_dir.mkdir(parents=True, exist_ok=True)
    return teams_dir


def create_team(
    name: str,
    agents: list[str],
    coordinator: str,
    goal: str,
) -> dict[str, Any]:
    """Create a team of agents with a designated coordinator.

    The team configuration is saved to ~/.pagal-os/teams/{name}.yaml.

    Args:
        name: Team name (used as filename).
        agents: List of agent names in the team.
        coordinator: Name of the coordinating agent (must be in agents list).
        goal: Description of the team's purpose.

    Returns:
        Dict with ok status and team info.
    """
    # Validate coordinator is in agents list
    if coordinator not in agents:
        agents = [coordinator] + agents

    # Validate all agents exist
    from src.core.runtime import load_agent

    missing = []
    for agent_name in agents:
        try:
            load_agent(agent_name)
        except FileNotFoundError:
            missing.append(agent_name)

    if missing:
        return {
            "ok": False,
            "error": f"Agents not found: {', '.join(missing)}. Create them first.",
        }

    team_config = {
        "name": name,
        "coordinator": coordinator,
        "agents": agents,
        "goal": goal,
    }

    teams_dir = _get_teams_dir()
    team_file = teams_dir / f"{name}.yaml"

    try:
        with open(team_file, "w", encoding="utf-8") as f:
            yaml.dump(team_config, f, default_flow_style=False, sort_keys=False)
        logger.info("Created team '%s' at %s", name, team_file)
    except Exception as e:
        logger.error("Failed to save team '%s': %s", name, e)
        return {"ok": False, "error": f"Failed to save team config: {e}"}

    return {
        "ok": True,
        "name": name,
        "coordinator": coordinator,
        "agents": agents,
        "goal": goal,
        "message": f"Team '{name}' created with {len(agents)} agents.",
    }


def _load_team(name: str) -> dict[str, Any]:
    """Load a team configuration from YAML.

    Args:
        name: Team name.

    Returns:
        Team configuration dict.

    Raises:
        FileNotFoundError: If the team config doesn't exist.
        ValueError: If the YAML is invalid.
    """
    teams_dir = _get_teams_dir()
    team_file = teams_dir / f"{name}.yaml"

    if not team_file.exists():
        raise FileNotFoundError(f"Team not found: {team_file}")

    try:
        with open(team_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid team YAML: {e}") from e

    return data


def list_teams() -> list[dict[str, Any]]:
    """List all defined teams.

    Returns:
        List of dicts with team name, coordinator, agents, and goal.
    """
    teams_dir = _get_teams_dir()
    teams = []

    for yaml_file in sorted(teams_dir.glob("*.yaml")):
        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            teams.append({
                "name": data.get("name", yaml_file.stem),
                "coordinator": data.get("coordinator", ""),
                "agents": data.get("agents", []),
                "goal": data.get("goal", ""),
            })
        except Exception as e:
            logger.warning("Failed to load team %s: %s", yaml_file, e)

    return teams


def tool_delegate(args: dict[str, Any]) -> dict[str, Any]:
    """Tool that a coordinator agent uses to delegate a subtask to another agent.

    This is registered as a tool so the LLM coordinator can call it.

    Args:
        args: Dict with 'agent_name' and 'subtask' keys.

    Returns:
        Dict with the agent's response.
    """
    agent_name = args.get("agent_name", "")
    subtask = args.get("subtask", "")

    if not agent_name or not subtask:
        return {"ok": False, "error": "Both 'agent_name' and 'subtask' are required."}

    try:
        from src.core.runtime import load_agent, run_agent

        agent = load_agent(agent_name)
        result = run_agent(agent, subtask)
        return {
            "ok": result.ok,
            "agent": agent_name,
            "output": result.output,
            "error": result.error,
            "duration_seconds": result.duration_seconds,
        }
    except Exception as e:
        logger.error("Delegation to '%s' failed: %s", agent_name, e)
        return {"ok": False, "agent": agent_name, "error": str(e)}


def _run_subtask(agent_name: str, subtask: str) -> dict[str, Any]:
    """Execute a single subtask on a specific agent.

    Args:
        agent_name: Name of the agent to run the subtask on.
        subtask: The subtask description.

    Returns:
        Dict with agent name, subtask, output, and status.
    """
    try:
        from src.core.runtime import load_agent, run_agent

        agent = load_agent(agent_name)
        result = run_agent(agent, subtask)
        return {
            "agent": agent_name,
            "subtask": subtask,
            "ok": result.ok,
            "output": result.output,
            "error": result.error,
            "duration_seconds": result.duration_seconds,
        }
    except Exception as e:
        logger.error("Subtask failed for agent '%s': %s", agent_name, e)
        return {
            "agent": agent_name,
            "subtask": subtask,
            "ok": False,
            "output": "",
            "error": str(e),
            "duration_seconds": 0.0,
        }


def run_team(team_name: str, task: str) -> dict[str, Any]:
    """Execute a team task using multi-agent collaboration.

    Workflow:
        1. Coordinator agent receives the task
        2. Coordinator breaks it into subtasks (via LLM)
        3. Each subtask assigned to the best agent
        4. Agents run in parallel (ThreadPoolExecutor)
        5. Results collected and sent back to coordinator
        6. Coordinator synthesizes final report

    Args:
        team_name: Name of the team to run.
        task: The task to execute.

    Returns:
        Dict with ok, report, subtasks, and agents_used.
    """
    # Load team config
    try:
        team = _load_team(team_name)
    except (FileNotFoundError, ValueError) as e:
        return {"ok": False, "report": "", "subtasks": [], "agents_used": [], "error": str(e)}

    coordinator_name = team.get("coordinator", "")
    available_agents = team.get("agents", [])
    goal = team.get("goal", "")

    if not coordinator_name or not available_agents:
        return {
            "ok": False,
            "report": "",
            "subtasks": [],
            "agents_used": [],
            "error": "Team is missing coordinator or agents.",
        }

    # Step 1 & 2: Ask coordinator to break task into subtasks
    from src.core.llm import call_llm
    from src.core.runtime import load_agent

    try:
        coordinator = load_agent(coordinator_name)
    except FileNotFoundError:
        return {
            "ok": False,
            "report": "",
            "subtasks": [],
            "agents_used": [],
            "error": f"Coordinator agent '{coordinator_name}' not found.",
        }

    planning_prompt = f"""You are the coordinator of a team with these agents: {', '.join(available_agents)}.

Team goal: {goal}

Task: {task}

Break this task into subtasks. For each subtask, assign it to the best agent from the team.

Return your plan as a JSON array (and NOTHING else) like this:
[
  {{"agent": "agent_name", "subtask": "what this agent should do"}},
  {{"agent": "agent_name", "subtask": "what this agent should do"}}
]

Rules:
- Each subtask should be clear and self-contained
- Assign to the agent whose name best matches the subtask
- Use 2-5 subtasks (not more)
- Return ONLY the JSON array, no other text"""

    planning_messages = [
        {"role": "system", "content": coordinator.personality},
        {"role": "user", "content": planning_prompt},
    ]

    plan_result = call_llm(
        messages=planning_messages,
        model=coordinator.model,
        timeout=30,
    )

    if not plan_result["ok"]:
        return {
            "ok": False,
            "report": "",
            "subtasks": [],
            "agents_used": [],
            "error": f"Coordinator planning failed: {plan_result['error']}",
        }

    # Parse the plan
    plan_text = plan_result["content"].strip()
    # Strip markdown code fences if present
    if plan_text.startswith("```"):
        lines = plan_text.split("\n")
        plan_text = "\n".join(
            line for line in lines
            if not line.strip().startswith("```")
        )

    try:
        subtasks_plan = json.loads(plan_text)
    except json.JSONDecodeError:
        # Try to extract JSON from the response
        import re
        json_match = re.search(r"\[.*\]", plan_text, re.DOTALL)
        if json_match:
            try:
                subtasks_plan = json.loads(json_match.group())
            except json.JSONDecodeError:
                return {
                    "ok": False,
                    "report": "",
                    "subtasks": [],
                    "agents_used": [],
                    "error": f"Could not parse coordinator's plan as JSON: {plan_text[:500]}",
                }
        else:
            return {
                "ok": False,
                "report": "",
                "subtasks": [],
                "agents_used": [],
                "error": f"Coordinator did not return a valid JSON plan: {plan_text[:500]}",
            }

    if not isinstance(subtasks_plan, list) or not subtasks_plan:
        return {
            "ok": False,
            "report": "",
            "subtasks": [],
            "agents_used": [],
            "error": "Coordinator returned an empty or invalid plan.",
        }

    # Validate agent names in plan -- fallback to coordinator for unknown agents
    for item in subtasks_plan:
        if item.get("agent") not in available_agents:
            item["agent"] = coordinator_name

    logger.info(
        "Team '%s' plan: %d subtasks across agents: %s",
        team_name,
        len(subtasks_plan),
        ", ".join(set(item["agent"] for item in subtasks_plan)),
    )

    # Step 3 & 4: Run subtasks in parallel
    subtask_results = []
    agents_used = set()

    with ThreadPoolExecutor(max_workers=min(len(subtasks_plan), 5)) as executor:
        future_to_task = {}
        for item in subtasks_plan:
            agent_name = item.get("agent", coordinator_name)
            subtask = item.get("subtask", "")
            if not subtask:
                continue
            future = executor.submit(_run_subtask, agent_name, subtask)
            future_to_task[future] = item

        for future in as_completed(future_to_task):
            try:
                result = future.result(timeout=300)
                subtask_results.append(result)
                agents_used.add(result["agent"])
            except Exception as e:
                original = future_to_task[future]
                subtask_results.append({
                    "agent": original.get("agent", "unknown"),
                    "subtask": original.get("subtask", ""),
                    "ok": False,
                    "output": "",
                    "error": str(e),
                })

    # Step 5 & 6: Send results back to coordinator for synthesis
    results_summary = []
    for r in subtask_results:
        status = "SUCCESS" if r.get("ok") else "FAILED"
        output = r.get("output", "")[:1500]  # Truncate long outputs
        error = r.get("error", "")
        results_summary.append(
            f"Agent: {r['agent']}\n"
            f"Subtask: {r['subtask']}\n"
            f"Status: {status}\n"
            f"Output: {output}\n"
            f"Error: {error}\n"
        )

    synthesis_prompt = f"""You are the coordinator of team '{team_name}'.

Original task: {task}

Your team completed these subtasks:

{'---'.join(results_summary)}

Now synthesize a comprehensive final report that:
1. Summarizes what was accomplished
2. Combines the key findings from all agents
3. Notes any failures or gaps
4. Provides a clear conclusion

Write the report directly -- no JSON, just clear text."""

    synthesis_messages = [
        {"role": "system", "content": coordinator.personality},
        {"role": "user", "content": synthesis_prompt},
    ]

    synthesis_result = call_llm(
        messages=synthesis_messages,
        model=coordinator.model,
        timeout=60,
    )

    if synthesis_result["ok"]:
        report = synthesis_result["content"]
    else:
        # Fallback: just concatenate results
        report = f"Coordinator synthesis failed ({synthesis_result['error']}). Raw results:\n\n"
        for r in subtask_results:
            report += f"[{r['agent']}] {r['subtask']}\n{r.get('output', r.get('error', ''))}\n\n"

    return {
        "ok": True,
        "report": report,
        "subtasks": [
            {
                "agent": r["agent"],
                "subtask": r["subtask"],
                "ok": r.get("ok", False),
                "output_preview": (r.get("output", "") or "")[:200],
                "error": r.get("error", ""),
            }
            for r in subtask_results
        ],
        "agents_used": sorted(agents_used),
    }


def delete_team(name: str) -> bool:
    """Delete a team configuration.

    Args:
        name: Team name to delete.

    Returns:
        True if deleted, False if not found.
    """
    teams_dir = _get_teams_dir()
    team_file = teams_dir / f"{name}.yaml"

    if team_file.exists():
        team_file.unlink()
        logger.info("Deleted team '%s'.", name)
        return True
    return False
