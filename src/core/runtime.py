"""PAGAL OS Agent Runtime — the kernel that loads, runs, and manages agents."""

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.core.config import get_config
from src.core.llm import call_llm
from src.tools.registry import execute_tool, get_tool_schemas

logger = logging.getLogger("pagal_os")

# Agent storage directory
AGENTS_DIR = Path.home() / ".pagal-os" / "agents"

# Track running agents: name -> {thread, status, started_at, result}
_running_agents: dict[str, dict[str, Any]] = {}


@dataclass
class AgentConfig:
    """Configuration for a single agent, loaded from YAML."""

    name: str
    description: str
    model: str
    tools: list[str] = field(default_factory=list)
    personality: str = "You are a helpful AI assistant."
    memory: bool = True
    schedule: str | None = None


@dataclass
class AgentResult:
    """Result of running an agent."""

    ok: bool
    output: str
    tools_used: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    error: str = ""


def load_agent(name: str) -> AgentConfig:
    """Load an agent configuration from its YAML file.

    Args:
        name: Agent name (without .yaml extension).

    Returns:
        Populated AgentConfig.

    Raises:
        FileNotFoundError: If the agent YAML file doesn't exist.
        ValueError: If the YAML is invalid.
    """
    config = get_config()
    agent_path = config.agents_dir / f"{name}.yaml"

    if not agent_path.exists():
        raise FileNotFoundError(f"Agent not found: {agent_path}")

    try:
        with open(agent_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in {agent_path}: {e}") from e

    return AgentConfig(
        name=data.get("name", name),
        description=data.get("description", ""),
        model=data.get("model", config.default_model),
        tools=data.get("tools", []),
        personality=data.get("personality", "You are a helpful AI assistant."),
        memory=data.get("memory", True),
        schedule=data.get("schedule"),
    )


def run_agent(agent: AgentConfig, task: str) -> AgentResult:
    """Execute an agent's task loop.

    Builds messages from the agent's personality, sends to LLM with tool schemas,
    and loops through tool calls until the LLM returns a final text response.

    Args:
        agent: The agent configuration.
        task: The user's task/prompt.

    Returns:
        AgentResult with output or error.
    """
    start_time = time.time()
    tools_used: list[str] = []
    max_loops = 20

    try:
        # Build initial messages
        messages: list[dict[str, str]] = [
            {"role": "system", "content": agent.personality},
            {"role": "user", "content": task},
        ]

        # Get tool schemas for this agent's tools
        tool_schemas = get_tool_schemas(agent.tools) if agent.tools else None

            # Resource tracking: start monitoring limits for this run
        try:
            from src.core.resources import (
                check_all_limits,
                start_tracking,
                stop_tracking,
                track_usage,
            )
            resource_limits = start_tracking(agent.name)
            tracking_enabled = True
        except Exception:
            tracking_enabled = False

        try:
            for loop_num in range(max_loops):
                # Check resource limits before each LLM call
                if tracking_enabled:
                    limit_exceeded = check_all_limits(resource_limits)
                    if limit_exceeded:
                        logger.warning(
                            "Agent '%s' stopped: %s", agent.name, limit_exceeded,
                        )
                        return AgentResult(
                            ok=False,
                            output="",
                            tools_used=tools_used,
                            duration_seconds=time.time() - start_time,
                            error=f"Resource limit exceeded: {limit_exceeded}",
                        )

                logger.info(
                    "Agent '%s' loop %d/%d",
                    agent.name, loop_num + 1, max_loops,
                )

                # Call LLM
                result = call_llm(
                    messages=messages,
                    model=agent.model,
                    tools=tool_schemas,
                    timeout=60,
                )

                if not result["ok"]:
                    return AgentResult(
                        ok=False,
                        output="",
                        tools_used=tools_used,
                        duration_seconds=time.time() - start_time,
                        error=result["error"],
                    )

                # Track token usage (estimate based on content length)
                if tracking_enabled:
                    content_len = len(result.get("content", "") or "")
                    estimated_tokens = max(content_len // 4, 50)
                    track_usage(agent.name, tokens=estimated_tokens)

                # If no tool calls, we have the final response
                if not result["tool_calls"]:
                    return AgentResult(
                        ok=True,
                        output=result["content"],
                        tools_used=tools_used,
                        duration_seconds=time.time() - start_time,
                    )

                # Process tool calls
                # Append the assistant's message with tool calls
                messages.append({
                    "role": "assistant",
                    "content": result["content"] or "",
                    "tool_calls": result["tool_calls"],
                })

                for tool_call in result["tool_calls"]:
                    # Check tool call limit before executing
                    if tracking_enabled:
                        limit_exceeded = check_all_limits(resource_limits)
                        if limit_exceeded:
                            logger.warning(
                                "Agent '%s' stopped mid-tools: %s",
                                agent.name, limit_exceeded,
                            )
                            return AgentResult(
                                ok=False,
                                output="",
                                tools_used=tools_used,
                                duration_seconds=time.time() - start_time,
                                error=f"Resource limit exceeded: {limit_exceeded}",
                            )

                    func_info = tool_call.get("function", {})
                    tool_name = func_info.get("name", "")
                    tool_args_str = func_info.get("arguments", "{}")

                    # Parse arguments
                    try:
                        tool_args = json.loads(tool_args_str) if isinstance(tool_args_str, str) else tool_args_str
                    except json.JSONDecodeError:
                        tool_args = {}

                    logger.info("Agent '%s' calling tool: %s(%s)", agent.name, tool_name, tool_args)

                    # Execute the tool
                    tool_result = execute_tool(tool_name, tool_args)
                    tools_used.append(tool_name)

                    # Track tool call usage
                    if tracking_enabled:
                        track_usage(agent.name, tool_calls=1)

                    # Append tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.get("id", ""),
                        "content": json.dumps(tool_result),
                    })

            # If we hit max loops, return what we have
            return AgentResult(
                ok=True,
                output=result.get("content", "Agent reached maximum loop count."),
                tools_used=tools_used,
                duration_seconds=time.time() - start_time,
            )
        finally:
            # Always stop resource tracking when the run ends
            if tracking_enabled:
                stop_tracking(agent.name)

    except Exception as e:
        logger.error("Agent '%s' crashed: %s", agent.name, e, exc_info=True)
        return AgentResult(
            ok=False,
            output="",
            tools_used=tools_used,
            duration_seconds=time.time() - start_time,
            error=str(e),
        )


def list_agents() -> list[dict[str, Any]]:
    """List all available agents from the agents directory.

    Returns:
        List of dicts with agent name, description, and status info.
    """
    config = get_config()
    agents = []

    if not config.agents_dir.exists():
        return agents

    for yaml_file in sorted(config.agents_dir.glob("*.yaml")):
        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            name = data.get("name", yaml_file.stem)
            status = get_agent_status(name)
            agents.append({
                "name": name,
                "description": data.get("description", ""),
                "model": data.get("model", ""),
                "tools": data.get("tools", []),
                "status": status.get("status", "idle"),
            })
        except Exception as e:
            logger.warning("Failed to load agent %s: %s", yaml_file, e)

    return agents


def get_agent_status(name: str) -> dict[str, Any]:
    """Get the current status of an agent.

    Args:
        name: Agent name.

    Returns:
        Dict with status ('running', 'idle', 'completed', 'error') and metadata.
    """
    if name in _running_agents:
        info = _running_agents[name]
        thread: threading.Thread = info.get("thread")
        if thread and thread.is_alive():
            return {
                "status": "running",
                "started_at": info.get("started_at", 0),
            }
        else:
            result: AgentResult | None = info.get("result")
            if result and not result.ok:
                return {"status": "error", "error": result.error}
            return {"status": "completed"}

    return {"status": "idle"}


def run_agent_async(name: str, task: str) -> dict[str, str]:
    """Run an agent in a background thread.

    Args:
        name: Agent name.
        task: The task to execute.

    Returns:
        Dict with status message.
    """
    if name in _running_agents:
        info = _running_agents[name]
        thread = info.get("thread")
        if thread and thread.is_alive():
            return {"status": "already_running", "message": f"Agent '{name}' is already running"}

    try:
        agent = load_agent(name)
    except (FileNotFoundError, ValueError) as e:
        return {"status": "error", "message": str(e)}

    def _run() -> None:
        """Background worker for agent execution."""
        result = run_agent(agent, task)
        _running_agents[name]["result"] = result
        _running_agents[name]["status"] = "completed" if result.ok else "error"

    thread = threading.Thread(target=_run, daemon=True, name=f"agent-{name}")
    _running_agents[name] = {
        "thread": thread,
        "status": "running",
        "started_at": time.time(),
        "result": None,
    }
    thread.start()

    return {"status": "started", "message": f"Agent '{name}' started"}


def stop_agent(name: str) -> bool:
    """Stop a running agent.

    Note: Python threads can't be forcefully killed. This removes tracking
    and lets the thread finish naturally.

    Args:
        name: Agent name.

    Returns:
        True if the agent was being tracked, False otherwise.
    """
    if name in _running_agents:
        del _running_agents[name]
        logger.info("Stopped tracking agent '%s'", name)
        return True
    return False


def delete_agent(name: str) -> bool:
    """Delete an agent's YAML file.

    Args:
        name: Agent name.

    Returns:
        True if deleted, False if not found.
    """
    config = get_config()
    agent_path = config.agents_dir / f"{name}.yaml"

    if agent_path.exists():
        agent_path.unlink()
        stop_agent(name)
        logger.info("Deleted agent '%s'", name)
        return True
    return False
