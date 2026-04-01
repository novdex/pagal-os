"""Natural Language Workflows -- describe automations in English.

'When I get an email, research the topic, draft a reply' -- described in
English, auto-built into structured workflow definitions.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.core.llm import call_llm

logger = logging.getLogger("pagal_os")

# Workflows storage directory
WORKFLOWS_DIR = Path.home() / ".pagal-os" / "workflows"


@dataclass
class Workflow:
    """A structured workflow definition parsed from natural language.

    Attributes:
        name: Short identifier for the workflow.
        trigger: How the workflow starts ('manual', 'schedule:every 1h', 'webhook:http').
        steps: Ordered list of step dicts, each with 'agent' and 'task' keys.
        description: Original natural language description.
    """

    name: str
    trigger: str  # "manual", "schedule:every 1h", "webhook:http"
    steps: list[dict[str, str]] = field(default_factory=list)
    description: str = ""


def create_workflow_from_description(description: str) -> dict[str, Any]:
    """Parse a natural language description into a structured workflow.

    Uses an LLM call to interpret the description and extract a workflow
    name, trigger, and ordered steps (each with an agent and task).

    Args:
        description: English description of the desired automation.

    Returns:
        Dict with 'ok', 'workflow' (serialized Workflow), and 'message'.
    """
    try:
        prompt = (
            "Parse this into a workflow definition. The user said:\n"
            f'"{description}"\n\n'
            "Return ONLY valid JSON with this exact structure (no markdown, no explanation):\n"
            '{"name": "short_name", "trigger": "manual", '
            '"steps": [{"agent": "agent_name", "task": "what to do"}]}\n\n'
            'For trigger, use "manual" unless the user specifies a schedule or webhook.\n'
            "For agent names, use descriptive names like 'research_agent', 'writer_agent', 'file_helper'.\n"
            "Break the workflow into 2-5 logical steps."
        )

        messages = [
            {"role": "system", "content": "You are a workflow parser. Return only valid JSON."},
            {"role": "user", "content": prompt},
        ]

        # Use the default free model for parsing
        from src.core.config import get_config
        config = get_config()

        result = call_llm(messages=messages, model=config.default_model, timeout=30)

        if not result["ok"]:
            return {"ok": False, "workflow": None, "message": f"LLM error: {result['error']}"}

        # Parse the JSON from LLM response
        content = result["content"].strip()
        # Strip markdown code fences if present
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            content = content.strip()

        parsed = json.loads(content)

        workflow = Workflow(
            name=parsed.get("name", "unnamed_workflow"),
            trigger=parsed.get("trigger", "manual"),
            steps=parsed.get("steps", []),
            description=description,
        )

        return {"ok": True, "workflow": _workflow_to_dict(workflow), "message": "Workflow created"}

    except json.JSONDecodeError as e:
        logger.error("Failed to parse LLM workflow response: %s", e)
        return {"ok": False, "workflow": None, "message": f"Failed to parse workflow: {e}"}
    except Exception as e:
        logger.error("Failed to create workflow from description: %s", e)
        return {"ok": False, "workflow": None, "message": str(e)}


def run_workflow(workflow: Workflow, input_data: str = "") -> dict[str, Any]:
    """Execute a workflow by running each step in sequence.

    Each step is run by loading the specified agent and passing it the task.
    The output of each step is appended to the context for the next step.

    Args:
        workflow: The Workflow object to execute.
        input_data: Optional initial input data to pass to the first step.

    Returns:
        Dict with 'ok', 'results' (list of step results), and 'final_output'.
    """
    try:
        from src.core.runtime import load_agent, run_agent

        results: list[dict[str, Any]] = []
        context = input_data
        all_ok = True

        for i, step in enumerate(workflow.steps):
            agent_name = step.get("agent", "")
            task = step.get("task", "")

            # Inject context from previous step
            if context:
                task = f"{task}\n\nContext from previous step:\n{context}"

            logger.info("Workflow '%s' step %d/%d: agent='%s'", workflow.name, i + 1, len(workflow.steps), agent_name)

            try:
                agent = load_agent(agent_name)
                result = run_agent(agent, task)
                step_result = {
                    "step": i + 1,
                    "agent": agent_name,
                    "task": step.get("task", ""),
                    "ok": result.ok,
                    "output": result.output,
                    "error": result.error,
                }
                context = result.output  # pass output to next step
            except FileNotFoundError:
                step_result = {
                    "step": i + 1,
                    "agent": agent_name,
                    "task": step.get("task", ""),
                    "ok": False,
                    "output": "",
                    "error": f"Agent '{agent_name}' not found",
                }
                all_ok = False
            except Exception as e:
                step_result = {
                    "step": i + 1,
                    "agent": agent_name,
                    "task": step.get("task", ""),
                    "ok": False,
                    "output": "",
                    "error": str(e),
                }
                all_ok = False

            results.append(step_result)

            # Stop on failure unless we want to continue
            if not step_result["ok"]:
                break

        return {
            "ok": all_ok,
            "workflow": workflow.name,
            "results": results,
            "final_output": context,
        }
    except Exception as e:
        logger.error("Failed to run workflow '%s': %s", workflow.name, e)
        return {"ok": False, "workflow": workflow.name, "results": [], "final_output": "", "error": str(e)}


def save_workflow(workflow: Workflow) -> bool:
    """Save a workflow definition to disk as YAML.

    Stores in ~/.pagal-os/workflows/{name}.yaml.

    Args:
        workflow: The Workflow to save.

    Returns:
        True if saved successfully, False on error.
    """
    try:
        WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
        path = WORKFLOWS_DIR / f"{workflow.name}.yaml"
        data = _workflow_to_dict(workflow)

        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        logger.info("Workflow '%s' saved to %s", workflow.name, path)
        return True
    except Exception as e:
        logger.error("Failed to save workflow '%s': %s", workflow.name, e)
        return False


def list_workflows() -> list[dict[str, Any]]:
    """List all saved workflows.

    Scans ~/.pagal-os/workflows/ for YAML files and returns a summary
    of each workflow.

    Returns:
        List of dicts with name, trigger, steps_count, and description.
    """
    try:
        WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)
        workflows: list[dict[str, Any]] = []

        for path in sorted(WORKFLOWS_DIR.glob("*.yaml")):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                workflows.append({
                    "name": data.get("name", path.stem),
                    "trigger": data.get("trigger", "manual"),
                    "steps_count": len(data.get("steps", [])),
                    "description": data.get("description", ""),
                })
            except Exception as e:
                logger.debug("Failed to load workflow %s: %s", path, e)

        return workflows
    except Exception as e:
        logger.error("Failed to list workflows: %s", e)
        return []


def load_workflow(name: str) -> Workflow:
    """Load a workflow from disk by name.

    Args:
        name: Workflow name (without .yaml extension).

    Returns:
        Workflow object.

    Raises:
        FileNotFoundError: If the workflow file doesn't exist.
    """
    path = WORKFLOWS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Workflow not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    return Workflow(
        name=data.get("name", name),
        trigger=data.get("trigger", "manual"),
        steps=data.get("steps", []),
        description=data.get("description", ""),
    )


def tool_create_workflow(args: dict[str, Any]) -> dict[str, Any]:
    """Tool wrapper for creating a workflow from natural language.

    Designed to be called as an agent tool. Parses the description,
    creates the workflow, and saves it to disk.

    Args:
        args: Dict with 'description' key containing the natural language input.

    Returns:
        Dict with workflow creation result.
    """
    try:
        description = args.get("description", "")
        if not description:
            return {"ok": False, "error": "No description provided"}

        result = create_workflow_from_description(description)
        if not result["ok"]:
            return result

        # Build workflow object and save
        wf_data = result["workflow"]
        workflow = Workflow(
            name=wf_data["name"],
            trigger=wf_data["trigger"],
            steps=wf_data["steps"],
            description=wf_data["description"],
        )
        save_workflow(workflow)

        return result
    except Exception as e:
        logger.error("tool_create_workflow failed: %s", e)
        return {"ok": False, "error": str(e)}


def _workflow_to_dict(workflow: Workflow) -> dict[str, Any]:
    """Convert a Workflow dataclass to a plain dict.

    Args:
        workflow: Workflow object to serialize.

    Returns:
        Dict representation suitable for YAML/JSON serialization.
    """
    return {
        "name": workflow.name,
        "trigger": workflow.trigger,
        "steps": workflow.steps,
        "description": workflow.description,
    }
