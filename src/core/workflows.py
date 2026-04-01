"""Natural Language Workflows -- describe automations in English.

'When I get an email, research the topic, draft a reply' -- described in
English, auto-built into structured workflow definitions.

Supports four step types:
- agent: Run an AI agent on a task (original).
- rule: Deterministic IF/THEN/ELSE logic using simple conditions.
- transform: Data operations (filter, sort, map, count).
- notify: Send notifications with template variable substitution.
"""

import json
import logging
import operator
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
        steps: Ordered list of step dicts. Each step has a 'type' key:
               - 'agent': {'agent': str, 'task': str}
               - 'rule': {'condition': str, 'then': str, 'else': str}
               - 'transform': {'action': str, 'field': str, 'operator': str, 'value': any}
               - 'notify': {'message': str}
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


def evaluate_rule(condition: str, context: dict[str, Any]) -> bool:
    """Evaluate a simple rule condition against a context dict.

    Supports operators: >, <, >=, <=, ==, !=, contains, startswith, endswith.
    The condition format is: 'field operator value' (e.g. 'price < 100').

    Args:
        condition: The condition string (e.g. 'rating > 4', 'name contains AI').
        context: Dict of variable names to values from previous step outputs.

    Returns:
        True if the condition is met, False otherwise.
    """
    try:
        # Parse condition into parts
        ops = {
            ">=": operator.ge,
            "<=": operator.le,
            "!=": operator.ne,
            "==": operator.eq,
            ">": operator.gt,
            "<": operator.lt,
            "contains": lambda a, b: str(b) in str(a),
            "startswith": lambda a, b: str(a).startswith(str(b)),
            "endswith": lambda a, b: str(a).endswith(str(b)),
        }

        # Try each operator (longest first to avoid '>' matching before '>=')
        for op_str, op_func in ops.items():
            if f" {op_str} " in condition:
                parts = condition.split(f" {op_str} ", 1)
                field_name = parts[0].strip()
                value_str = parts[1].strip()

                # Get field value from context
                field_value = context.get(field_name, field_name)

                # Try to parse value as number
                try:
                    compare_value: Any = float(value_str)
                    field_value = float(field_value)
                except (ValueError, TypeError):
                    compare_value = value_str.strip("'\"")

                return bool(op_func(field_value, compare_value))

        logger.warning("Could not parse condition: '%s'", condition)
        return False
    except Exception as e:
        logger.error("Rule evaluation failed for '%s': %s", condition, e)
        return False


def execute_transform(action: str, data: Any, params: dict[str, Any]) -> Any:
    """Execute a data transformation operation.

    Supported actions:
    - filter: Filter list items where field matches operator/value.
    - sort: Sort list by a field (ascending by default).
    - map: Extract a single field from each item in a list.
    - count: Return the count of items.

    Args:
        action: The transform action ('filter', 'sort', 'map', 'count').
        data: The data to transform (usually a list of dicts).
        params: Transform parameters (field, operator, value, reverse, etc.).

    Returns:
        The transformed data.
    """
    try:
        if action == "filter":
            field_name = params.get("field", "")
            op_str = params.get("operator", "==")
            value = params.get("value")

            if not isinstance(data, list):
                return data

            ops_map = {
                ">": operator.gt, "<": operator.lt,
                ">=": operator.ge, "<=": operator.le,
                "==": operator.eq, "!=": operator.ne,
            }
            op_func = ops_map.get(op_str, operator.eq)

            result = []
            for item in data:
                if isinstance(item, dict):
                    item_val = item.get(field_name)
                    try:
                        if op_func(float(item_val), float(value)):
                            result.append(item)
                    except (ValueError, TypeError):
                        if op_func(str(item_val), str(value)):
                            result.append(item)
            return result

        elif action == "sort":
            field_name = params.get("field", "")
            reverse = params.get("reverse", False)

            if not isinstance(data, list):
                return data

            try:
                return sorted(data, key=lambda x: x.get(field_name, 0) if isinstance(x, dict) else x, reverse=reverse)
            except (TypeError, AttributeError):
                return data

        elif action == "map":
            field_name = params.get("field", "")

            if not isinstance(data, list):
                return data

            return [item.get(field_name, None) if isinstance(item, dict) else item for item in data]

        elif action == "count":
            if isinstance(data, list):
                return len(data)
            elif isinstance(data, dict):
                return len(data)
            elif isinstance(data, str):
                return len(data)
            return 0

        else:
            logger.warning("Unknown transform action: '%s'", action)
            return data
    except Exception as e:
        logger.error("Transform '%s' failed: %s", action, e)
        return data


def execute_notify(message: str, context: dict[str, Any]) -> dict[str, Any]:
    """Send a notification with template variable substitution.

    Replaces {variable} placeholders in the message with values from context.
    Also attempts to send via the notifications system if available.

    Args:
        message: Message template with {variable} placeholders.
        context: Dict of variable values for substitution.

    Returns:
        Dict with 'ok', 'message' (the resolved message), and 'sent' flag.
    """
    try:
        # Replace template variables
        resolved = message
        for key, value in context.items():
            placeholder = f"{{{key}}}"
            if placeholder in resolved:
                resolved = resolved.replace(placeholder, str(value))

        logger.info("Workflow notification: %s", resolved)

        # Try to send via notifications system
        sent = False
        try:
            from src.core.notifications import send_notification
            send_notification("info", "workflow", resolved)
            sent = True
        except Exception:
            pass

        return {"ok": True, "message": resolved, "sent": sent}
    except Exception as e:
        logger.error("Notification failed: %s", e)
        return {"ok": False, "error": str(e)}


def run_workflow(workflow: Workflow, input_data: str = "") -> dict[str, Any]:
    """Execute a workflow by running each step in sequence.

    Supports four step types:
    - 'agent' (default): Run an AI agent on a task.
    - 'rule': Evaluate a condition and choose 'then' or 'else' as output.
    - 'transform': Apply data transformations (filter, sort, map, count).
    - 'notify': Send a notification with template variables.

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
        # Build a context dict for rule evaluation and template substitution
        context_dict: dict[str, Any] = {"input": input_data, "result": input_data}
        all_ok = True

        for i, step in enumerate(workflow.steps):
            step_type = step.get("type", "agent")

            logger.info(
                "Workflow '%s' step %d/%d: type='%s'",
                workflow.name, i + 1, len(workflow.steps), step_type,
            )

            try:
                if step_type == "agent":
                    # --- AI Agent Step ---
                    agent_name = step.get("agent", "")
                    task = step.get("task", "")

                    # Inject context from previous step
                    if context:
                        task = f"{task}\n\nContext from previous step:\n{context}"

                    agent = load_agent(agent_name)
                    result = run_agent(agent, task)
                    step_result = {
                        "step": i + 1,
                        "type": "agent",
                        "agent": agent_name,
                        "task": step.get("task", ""),
                        "ok": result.ok,
                        "output": result.output,
                        "error": result.error,
                    }
                    context = result.output
                    context_dict["result"] = result.output

                elif step_type == "rule":
                    # --- Deterministic Rule Step ---
                    condition = step.get("condition", "")
                    then_val = step.get("then", "")
                    else_val = step.get("else", "")

                    rule_result = evaluate_rule(condition, context_dict)
                    output = then_val if rule_result else else_val

                    step_result = {
                        "step": i + 1,
                        "type": "rule",
                        "condition": condition,
                        "evaluated": rule_result,
                        "ok": True,
                        "output": output,
                        "error": "",
                    }
                    context = output
                    context_dict["result"] = output
                    context_dict["rule_result"] = rule_result

                elif step_type == "transform":
                    # --- Data Transform Step ---
                    action = step.get("action", "")
                    params = {
                        k: v for k, v in step.items()
                        if k not in ("type", "action")
                    }

                    # Try to parse context as JSON for data operations
                    data_input: Any = context
                    try:
                        data_input = json.loads(context) if isinstance(context, str) else context
                    except (json.JSONDecodeError, TypeError):
                        pass

                    transformed = execute_transform(action, data_input, params)
                    output_str = json.dumps(transformed) if not isinstance(transformed, str) else transformed

                    step_result = {
                        "step": i + 1,
                        "type": "transform",
                        "action": action,
                        "ok": True,
                        "output": output_str,
                        "error": "",
                    }
                    context = output_str
                    context_dict["result"] = transformed

                elif step_type == "notify":
                    # --- Notification Step ---
                    message = step.get("message", "")
                    notify_result = execute_notify(message, context_dict)

                    step_result = {
                        "step": i + 1,
                        "type": "notify",
                        "ok": notify_result.get("ok", False),
                        "output": notify_result.get("message", ""),
                        "error": notify_result.get("error", ""),
                    }
                    # Don't change context for notify steps

                else:
                    step_result = {
                        "step": i + 1,
                        "type": step_type,
                        "ok": False,
                        "output": "",
                        "error": f"Unknown step type: '{step_type}'",
                    }
                    all_ok = False

            except FileNotFoundError:
                step_result = {
                    "step": i + 1,
                    "type": step_type,
                    "ok": False,
                    "output": "",
                    "error": f"Agent '{step.get('agent', '')}' not found",
                }
                all_ok = False
            except Exception as e:
                step_result = {
                    "step": i + 1,
                    "type": step_type,
                    "ok": False,
                    "output": "",
                    "error": str(e),
                }
                all_ok = False

            results.append(step_result)

            # Update context_dict with step output
            context_dict[f"step_{i + 1}"] = step_result.get("output", "")

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
