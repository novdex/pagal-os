"""PAGAL OS Agent Creator — generates agent YAML configs from natural language."""

import logging
import re
from pathlib import Path

import yaml

from src.core.config import get_config
from src.core.llm import call_llm
from src.tools.registry import list_tools

logger = logging.getLogger("pagal_os")


def create_agent_from_description(
    description: str,
    model: str | None = None,
) -> str:
    """Create an agent YAML config from a plain English description.

    Calls the LLM to generate a valid YAML agent config, parses the response,
    and saves it to ~/.pagal-os/agents/{name}.yaml.

    Args:
        description: Natural language description of what the agent should do.
        model: LLM model to use for generation. Defaults to config default.

    Returns:
        The agent name (filename stem).

    Raises:
        ValueError: If the LLM response can't be parsed as valid YAML.
        RuntimeError: If the LLM call fails entirely.
    """
    config = get_config()
    model = model or config.default_model
    available_tools = list_tools()

    prompt = f"""Create a YAML agent configuration for the following description:

"{description}"

Available tools: {', '.join(available_tools) if available_tools else 'search_web, browse_url, read_file, write_file, run_shell'}

Return ONLY valid YAML with these exact keys:
- name: a snake_case name for the agent (no spaces)
- description: a one-line description of what the agent does
- model: "{config.default_model}"
- tools: list of tool names from the available tools above
- personality: a detailed system prompt for the agent (2-3 sentences)
- memory: true or false
- schedule: null

Do NOT include any markdown formatting, code fences, or extra text. Return ONLY the YAML."""

    messages = [
        {"role": "system", "content": "You generate YAML configurations. Return ONLY valid YAML, nothing else."},
        {"role": "user", "content": prompt},
    ]

    result = call_llm(messages=messages, model=model, timeout=30)

    if not result["ok"]:
        raise RuntimeError(f"LLM call failed: {result['error']}")

    content = result["content"].strip()

    # Strip markdown code fences if present
    content = _strip_code_fences(content)

    # Parse YAML
    try:
        agent_data = yaml.safe_load(content)
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse LLM response as YAML: {e}\nResponse: {content}") from e

    if not isinstance(agent_data, dict):
        raise ValueError(f"Expected YAML dict, got: {type(agent_data)}")

    # Validate required fields
    name = agent_data.get("name")
    if not name:
        raise ValueError("Agent YAML missing 'name' field")

    # Sanitize name to be a valid filename
    name = re.sub(r"[^a-z0-9_]", "_", name.lower().strip())
    agent_data["name"] = name

    # Set defaults for missing fields
    agent_data.setdefault("description", description)
    agent_data.setdefault("model", config.default_model)
    agent_data.setdefault("tools", [])
    agent_data.setdefault("personality", "You are a helpful AI assistant.")
    agent_data.setdefault("memory", True)
    agent_data.setdefault("schedule", None)

    # Save to agents directory
    agent_path = config.agents_dir / f"{name}.yaml"
    try:
        with open(agent_path, "w", encoding="utf-8") as f:
            yaml.dump(agent_data, f, default_flow_style=False, sort_keys=False)
        logger.info("Created agent '%s' at %s", name, agent_path)
    except Exception as e:
        raise RuntimeError(f"Failed to save agent YAML: {e}") from e

    return name


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences from LLM output.

    Args:
        text: Raw LLM response text.

    Returns:
        Cleaned text without code fences.
    """
    # Remove ```yaml ... ``` or ``` ... ```
    text = re.sub(r"^```(?:yaml|yml)?\s*\n", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n```\s*$", "", text, flags=re.MULTILINE)
    return text.strip()
