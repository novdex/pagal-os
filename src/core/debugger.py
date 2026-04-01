"""Agent Debugger -- step through agent reasoning step by step.

Provides a debugging interface that lets you pause, inspect, and resume
agent execution, similar to a code debugger.
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import yaml

from src.core.config import get_config
from src.core.llm import call_llm
from src.tools.registry import execute_tool, get_tool_schemas

logger = logging.getLogger("pagal_os")

# Active debug sessions: session_id -> DebugState
_debug_sessions: dict[str, "DebugState"] = {}


@dataclass
class DebugState:
    """State of an active debug session.

    Attributes:
        session_id: Unique identifier for this session.
        agent_name: Name of the agent being debugged.
        task: The original task string.
        current_step: Step counter (0-indexed).
        messages: Full message history for the LLM conversation.
        tool_calls: Pending tool calls from the last LLM response.
        status: Current session status ('paused', 'running', 'done', 'error').
        breakpoints: Set of event types to break on.
        log: Full history of all debug steps.
        model: Model to use for LLM calls.
        tool_schemas: Tool schemas available to the agent.
        last_llm_response: The raw last LLM response dict.
        tools_used: List of tool names used so far.
    """

    session_id: str = ""
    agent_name: str = ""
    task: str = ""
    current_step: int = 0
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    status: str = "paused"  # paused, running, done, error
    breakpoints: set[str] = field(default_factory=set)
    log: list[dict[str, Any]] = field(default_factory=list)
    model: str = ""
    tool_schemas: list[dict] | None = None
    last_llm_response: dict[str, Any] = field(default_factory=dict)
    tools_used: list[str] = field(default_factory=list)


def start_debug_session(agent_name: str, task: str) -> str:
    """Initialize a new debug session for an agent + task.

    Loads the agent configuration, sets up the initial messages, and
    returns a session ID. The session starts in 'paused' state.

    Args:
        agent_name: Name of the agent to debug.
        task: The task to execute in debug mode.

    Returns:
        The debug session ID string.

    Raises:
        FileNotFoundError: If the agent YAML doesn't exist.
    """
    try:
        from src.core.runtime import load_agent

        agent = load_agent(agent_name)
        session_id = f"dbg-{uuid.uuid4().hex[:8]}"

        state = DebugState(
            session_id=session_id,
            agent_name=agent_name,
            task=task,
            model=agent.model,
            tool_schemas=get_tool_schemas(agent.tools) if agent.tools else None,
            messages=[
                {"role": "system", "content": agent.personality},
                {"role": "user", "content": task},
            ],
        )

        state.log.append({
            "step": 0,
            "type": "session_start",
            "content": f"Debug session started for '{agent_name}' with task: {task[:100]}",
            "timestamp": time.time(),
        })

        _debug_sessions[session_id] = state
        logger.info("Debug session %s started for agent '%s'", session_id, agent_name)
        return session_id

    except Exception as e:
        logger.error("Failed to start debug session: %s", e)
        raise


def step(session_id: str) -> dict[str, Any]:
    """Execute ONE step in the debug session, then pause.

    A step is either:
    - An LLM call (if no pending tool calls)
    - A tool execution (if there are pending tool calls)

    Args:
        session_id: The debug session ID.

    Returns:
        Dict with current state snapshot after the step.
    """
    state = _debug_sessions.get(session_id)
    if not state:
        return {"ok": False, "error": f"Session '{session_id}' not found"}

    if state.status == "done":
        return {"ok": False, "error": "Session already completed"}

    state.status = "running"
    state.current_step += 1

    try:
        if state.tool_calls:
            # Execute the next pending tool call
            return _step_tool_call(state)
        else:
            # Make an LLM call
            return _step_llm_call(state)
    except Exception as e:
        state.status = "error"
        state.log.append({
            "step": state.current_step,
            "type": "error",
            "content": str(e),
            "timestamp": time.time(),
        })
        return {"ok": False, "error": str(e), "state": _state_snapshot(state)}


def inspect(session_id: str) -> dict[str, Any]:
    """Show current state without advancing the session.

    Includes messages so far, last LLM response, pending tool calls,
    and the full debug log.

    Args:
        session_id: The debug session ID.

    Returns:
        Dict with complete current state.
    """
    state = _debug_sessions.get(session_id)
    if not state:
        return {"ok": False, "error": f"Session '{session_id}' not found"}

    return {
        "ok": True,
        "session_id": state.session_id,
        "agent_name": state.agent_name,
        "task": state.task,
        "status": state.status,
        "current_step": state.current_step,
        "messages": state.messages,
        "pending_tool_calls": state.tool_calls,
        "last_llm_response": state.last_llm_response,
        "tools_used": state.tools_used,
        "breakpoints": list(state.breakpoints),
        "log": state.log,
    }


def continue_debug(session_id: str) -> dict[str, Any]:
    """Run until the next breakpoint or completion.

    Keeps stepping through the session until a breakpoint is hit,
    the agent finishes, or max steps (50) is reached.

    Args:
        session_id: The debug session ID.

    Returns:
        Dict with final state after stopping.
    """
    state = _debug_sessions.get(session_id)
    if not state:
        return {"ok": False, "error": f"Session '{session_id}' not found"}

    max_steps = 50
    for _ in range(max_steps):
        if state.status == "done":
            break

        result = step(session_id)

        if not result.get("ok"):
            break

        # Check breakpoints
        last_log = state.log[-1] if state.log else {}
        event_type = last_log.get("type", "")

        if event_type in state.breakpoints:
            state.status = "paused"
            break

        # Check for specific tool breakpoint
        if event_type == "tool_call":
            tool_name = last_log.get("tool_name", "")
            if tool_name in state.breakpoints:
                state.status = "paused"
                break

    return {"ok": True, "state": _state_snapshot(state)}


def set_breakpoint(session_id: str, on: str) -> bool:
    """Add a breakpoint to the debug session.

    Break on: 'tool_call', 'llm_call', 'error', or a specific tool name.

    Args:
        session_id: The debug session ID.
        on: Event type or tool name to break on.

    Returns:
        True if the breakpoint was set, False if session not found.
    """
    state = _debug_sessions.get(session_id)
    if not state:
        return False

    state.breakpoints.add(on)
    state.log.append({
        "step": state.current_step,
        "type": "breakpoint_set",
        "content": f"Breakpoint set on: {on}",
        "timestamp": time.time(),
    })
    logger.info("Breakpoint set on '%s' for session %s", on, session_id)
    return True


def modify_context(session_id: str, new_message: str) -> bool:
    """Inject a message into the conversation mid-debug.

    Useful for testing different conversation paths without restarting.

    Args:
        session_id: The debug session ID.
        new_message: The message content to inject as a 'user' message.

    Returns:
        True if the message was injected, False if session not found.
    """
    state = _debug_sessions.get(session_id)
    if not state:
        return False

    state.messages.append({"role": "user", "content": new_message})
    state.log.append({
        "step": state.current_step,
        "type": "context_modified",
        "content": f"Injected user message: {new_message[:100]}",
        "timestamp": time.time(),
    })
    logger.info("Context modified in session %s", session_id)
    return True


def get_debug_log(session_id: str) -> list[dict[str, Any]]:
    """Get the full debug log for a session.

    Args:
        session_id: The debug session ID.

    Returns:
        List of log entry dicts, or empty list if session not found.
    """
    state = _debug_sessions.get(session_id)
    if not state:
        return []
    return state.log


def list_debug_sessions() -> list[dict[str, Any]]:
    """List all active debug sessions.

    Returns:
        List of session summary dicts.
    """
    return [
        {
            "session_id": s.session_id,
            "agent_name": s.agent_name,
            "task": s.task[:60],
            "status": s.status,
            "current_step": s.current_step,
        }
        for s in _debug_sessions.values()
    ]


def _step_llm_call(state: DebugState) -> dict[str, Any]:
    """Execute an LLM call step.

    Args:
        state: The current debug state.

    Returns:
        Dict with step result and state snapshot.
    """
    start = time.time()
    result = call_llm(
        messages=state.messages,
        model=state.model,
        tools=state.tool_schemas,
        timeout=60,
    )
    duration_ms = int((time.time() - start) * 1000)

    state.last_llm_response = result

    state.log.append({
        "step": state.current_step,
        "type": "llm_call",
        "content": (result.get("content") or "")[:300],
        "duration_ms": duration_ms,
        "ok": result["ok"],
        "has_tool_calls": bool(result.get("tool_calls")),
        "timestamp": time.time(),
    })

    if not result["ok"]:
        state.status = "error"
        return {"ok": False, "error": result["error"], "state": _state_snapshot(state)}

    # Check if done (no tool calls = final response)
    if not result["tool_calls"]:
        state.status = "done"
        state.messages.append({"role": "assistant", "content": result["content"]})
        return {
            "ok": True,
            "type": "final_response",
            "content": result["content"],
            "state": _state_snapshot(state),
        }

    # Has tool calls -- queue them and pause
    state.messages.append({
        "role": "assistant",
        "content": result["content"] or "",
        "tool_calls": result["tool_calls"],
    })
    state.tool_calls = list(result["tool_calls"])
    state.status = "paused"

    return {
        "ok": True,
        "type": "llm_call",
        "content": result["content"],
        "pending_tool_calls": [
            tc.get("function", {}).get("name", "") for tc in state.tool_calls
        ],
        "state": _state_snapshot(state),
    }


def _step_tool_call(state: DebugState) -> dict[str, Any]:
    """Execute the next pending tool call step.

    Args:
        state: The current debug state.

    Returns:
        Dict with tool execution result and state snapshot.
    """
    if not state.tool_calls:
        return {"ok": False, "error": "No pending tool calls"}

    tool_call = state.tool_calls.pop(0)
    func_info = tool_call.get("function", {})
    tool_name = func_info.get("name", "")
    tool_args_str = func_info.get("arguments", "{}")

    try:
        tool_args = json.loads(tool_args_str) if isinstance(tool_args_str, str) else tool_args_str
    except json.JSONDecodeError:
        tool_args = {}

    logger.info("Debug step: executing tool %s(%s)", tool_name, tool_args)

    start = time.time()
    tool_result = execute_tool(tool_name, tool_args)
    duration_ms = int((time.time() - start) * 1000)

    state.tools_used.append(tool_name)

    state.log.append({
        "step": state.current_step,
        "type": "tool_call",
        "tool_name": tool_name,
        "tool_args": tool_args,
        "tool_result": str(tool_result)[:500],
        "duration_ms": duration_ms,
        "timestamp": time.time(),
    })

    # Append tool result to messages
    state.messages.append({
        "role": "tool",
        "tool_call_id": tool_call.get("id", ""),
        "content": json.dumps(tool_result),
    })

    # If no more pending tool calls, pause for next LLM call
    if not state.tool_calls:
        state.status = "paused"

    return {
        "ok": True,
        "type": "tool_call",
        "tool_name": tool_name,
        "tool_args": tool_args,
        "tool_result": tool_result,
        "remaining_tool_calls": len(state.tool_calls),
        "state": _state_snapshot(state),
    }


def _state_snapshot(state: DebugState) -> dict[str, Any]:
    """Create a compact snapshot of the debug state for API responses.

    Args:
        state: The debug state to snapshot.

    Returns:
        Dict with key state fields.
    """
    return {
        "session_id": state.session_id,
        "agent_name": state.agent_name,
        "status": state.status,
        "current_step": state.current_step,
        "message_count": len(state.messages),
        "pending_tool_calls": len(state.tool_calls),
        "tools_used": state.tools_used,
        "breakpoints": list(state.breakpoints),
    }
