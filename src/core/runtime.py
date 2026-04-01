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
    budget: dict | None = None


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
        budget=data.get("budget"),
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

    # --- Process Manager: register this run ---
    process_pid = ""
    try:
        from src.core.process_manager import register_process, update_process
        process_pid = register_process(agent.name, task, threading.current_thread())
        pm_enabled = True
    except Exception:
        pm_enabled = False

    # --- Observability: start a trace for this run ---
    trace_run_id = ""
    try:
        from src.core.observability import log_trace, start_trace
        trace_run_id = start_trace(agent.name)
        tracing_enabled = True
    except Exception:
        tracing_enabled = False

    # --- Cross-Session Memory: generate session ID and inject context ---
    session_id = ""
    try:
        from src.core.memory import (
            generate_session_id,
            get_memory_context,
            save_message,
            summarize_old_messages,
        )
        session_id = generate_session_id()
        memory_enabled = True
    except Exception:
        memory_enabled = False

    # --- Approval Gates: determine mode from agent YAML ---
    approval_mode = "ask"  # default
    try:
        config = get_config()
        agent_path = config.agents_dir / f"{agent.name}.yaml"
        if agent_path.exists():
            with open(agent_path, "r", encoding="utf-8") as _f:
                _agent_yaml = yaml.safe_load(_f) or {}
            approval_mode = _agent_yaml.get("approval_mode", "ask")
    except Exception:
        pass

    try:
        from src.core.approval import needs_approval, request_approval
        approval_enabled = True
    except Exception:
        approval_enabled = False

    # --- Rate Limiter: check before starting ---
    try:
        from src.core.rate_limiter import check_rate_limit, record_call
        rate_limiter_enabled = True
    except Exception:
        rate_limiter_enabled = False

    # --- Budget Governor: check before starting ---
    budget_ok = True
    try:
        from src.core.budget import check_budget
        budget_status = check_budget(agent.name)
        if not budget_status["ok"]:
            logger.warning("Agent '%s' budget exceeded", agent.name)
            # --- Notifications: budget limit hit ---
            try:
                from src.core.notifications import send_notification
                send_notification(
                    "error", agent.name,
                    f"Hit daily budget limit (${budget_status['daily_spent']:.4f}/${budget_status['daily_limit']:.2f})",
                )
            except Exception:
                pass
            return AgentResult(
                ok=False,
                output="",
                tools_used=tools_used,
                duration_seconds=time.time() - start_time,
                error=(
                    f"Budget limit reached. Daily: ${budget_status['daily_spent']:.4f}"
                    f"/${budget_status['daily_limit']:.2f}, "
                    f"Monthly: ${budget_status['monthly_spent']:.4f}"
                    f"/${budget_status['monthly_limit']:.2f}"
                ),
            )
        budget_enabled = True
    except Exception:
        budget_enabled = False

    # --- Agent Registry: auto-register on run ---
    try:
        from src.core.registry import record_agent_run, verify_agent
        if not verify_agent(agent.name):
            from src.core.registry import register_agent as _register
            _register(agent.name)
        registry_enabled = True
    except Exception:
        registry_enabled = False

    # --- Model Router: auto-select model if set to 'auto' ---
    try:
        from src.core.model_router import select_model
        if agent.model.lower() == "auto":
            agent.model = select_model(task, agent)
            logger.info("Model router selected '%s' for agent '%s'", agent.model, agent.name)
    except Exception as e:
        logger.debug("Model routing skipped: %s", e)

    try:
        # --- Security: scan prompt injection on user task ---
        try:
            from src.core.security import (
                audit_log,
                check_file_access,
                rate_limit,
                sanitize_tool_input,
                scan_prompt_injection,
            )
            security_enabled = True

            injection = scan_prompt_injection(task)
            if not injection["safe"]:
                audit_log("prompt_injection_blocked", agent.name, str(injection["threats"]))
                logger.warning("Prompt injection blocked for agent '%s'", agent.name)
                return AgentResult(
                    ok=False,
                    output="",
                    tools_used=tools_used,
                    duration_seconds=time.time() - start_time,
                    error=f"Prompt injection detected: {injection['threats']}",
                )

            # Rate limit check
            if not rate_limit(agent.name):
                audit_log("rate_limit_exceeded", agent.name, "")
                return AgentResult(
                    ok=False,
                    output="",
                    tools_used=tools_used,
                    duration_seconds=time.time() - start_time,
                    error="Rate limit exceeded",
                )

            audit_log("agent_started", agent.name, f"task={task[:100]}")
        except ImportError:
            security_enabled = False
        except Exception:
            security_enabled = False

        # Build initial messages — inject memory context into system prompt
        system_content = agent.personality
        if memory_enabled:
            try:
                memory_ctx = get_memory_context(agent.name)
                if memory_ctx:
                    system_content = f"{agent.personality}\n\n{memory_ctx}"
            except Exception as mem_err:
                logger.debug("Failed to inject memory context: %s", mem_err)

        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": task},
        ]

        # Save user message to memory
        if memory_enabled:
            try:
                save_message(agent.name, session_id, "user", task)
            except Exception:
                pass

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

        # --- Health Monitor: enable heartbeat tracking ---
        try:
            from src.core.health import record_heartbeat, record_error as _record_health_error
            health_enabled = True
            record_heartbeat(agent.name)
        except Exception:
            health_enabled = False

        try:
            for loop_num in range(max_loops):
                # --- Health: send heartbeat every loop iteration ---
                if health_enabled:
                    try:
                        record_heartbeat(agent.name)
                    except Exception:
                        pass

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

                # --- Rate Limiter: check before LLM call ---
                if rate_limiter_enabled:
                    try:
                        rl_status = check_rate_limit(agent.name)
                        if not rl_status["allowed"]:
                            wait_secs = rl_status["retry_after_seconds"]
                            logger.warning(
                                "Rate limit hit for '%s', waiting %ds",
                                agent.name, wait_secs,
                            )
                            time.sleep(min(wait_secs, 30))
                        record_call(agent.name)
                    except Exception:
                        pass

                # Call LLM (with self-healing on failure)
                _llm_start = time.time()
                result = call_llm(
                    messages=messages,
                    model=agent.model,
                    tools=tool_schemas,
                    timeout=60,
                )
                _llm_dur = int((time.time() - _llm_start) * 1000)

                # --- Trace: log LLM call ---
                if tracing_enabled:
                    try:
                        _llm_summary = (result.get("content") or "")[:200]
                        log_trace(
                            trace_run_id, agent.name, "llm_call",
                            f"Model={agent.model} | Response: {_llm_summary}",
                            duration_ms=_llm_dur,
                            tokens=estimated_tokens if 'estimated_tokens' in dir() else 0,
                        )
                    except Exception:
                        pass

                if not result["ok"]:
                    # --- Self-Healing: try to recover from LLM failure ---
                    try:
                        from src.core.healing import heal_llm_failure
                        result = heal_llm_failure(
                            model=agent.model,
                            messages=messages,
                            error=result["error"],
                            tools=tool_schemas,
                        )
                    except Exception:
                        pass  # healing itself failed, keep original error

                if not result["ok"]:
                    if pm_enabled:
                        update_process(process_pid, status="error", error=result["error"])
                    return AgentResult(
                        ok=False,
                        output="",
                        tools_used=tools_used,
                        duration_seconds=time.time() - start_time,
                        error=result["error"],
                    )

                # Track token usage — count input and output separately
                from src.core.budget import estimate_tokens as _est_tokens

                # Input tokens: sum of all message content sent to the LLM
                _input_tok = sum(
                    _est_tokens(m.get("content", "") or "")
                    for m in messages
                )
                # Output tokens: the response content
                _output_content = result.get("content", "") or ""
                _output_tok = _est_tokens(_output_content)
                estimated_tokens = _input_tok + _output_tok

                if tracking_enabled:
                    track_usage(agent.name, tokens=estimated_tokens)
                if pm_enabled:
                    update_process(process_pid, tokens=estimated_tokens)

                # --- Budget Governor: track cost after each LLM call ---
                if budget_enabled:
                    try:
                        from src.core.budget import check_budget as _recheck, track_cost
                        track_cost(
                            agent.name, estimated_tokens, agent.model,
                            input_tokens=_input_tok, output_tokens=_output_tok,
                        )
                        _budget = _recheck(agent.name)
                        if not _budget["ok"]:
                            logger.warning("Agent '%s' stopped: budget exceeded mid-run", agent.name)
                            return AgentResult(
                                ok=False,
                                output="",
                                tools_used=tools_used,
                                duration_seconds=time.time() - start_time,
                                error="Budget limit reached during execution",
                            )
                    except Exception:
                        pass

                # If no tool calls, we have the final response
                if not result["tool_calls"]:
                    # --- Knowledge: save key findings ---
                    _save_run_knowledge(agent.name, task, result["content"])

                    if security_enabled:
                        audit_log("agent_completed", agent.name, f"duration={time.time() - start_time:.1f}s")

                    # --- Memory: save assistant response ---
                    if memory_enabled:
                        try:
                            save_message(agent.name, session_id, "assistant", result["content"])
                        except Exception:
                            pass

                    # --- Process Manager: mark completed ---
                    if pm_enabled:
                        update_process(process_pid, status="completed")

                    # --- Analytics: record successful run ---
                    _record_analytics(
                        agent.name, task, True,
                        time.time() - start_time, estimated_tokens,
                        len(tools_used), "",
                    )

                    # --- Registry: record run ---
                    if registry_enabled:
                        try:
                            record_agent_run(agent.name)
                        except Exception:
                            pass

                    # --- Notifications: agent completed ---
                    try:
                        from src.core.notifications import send_notification
                        send_notification(
                            "completed", agent.name,
                            f"Task completed in {time.time() - start_time:.1f}s",
                        )
                    except Exception:
                        pass

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

                    # --- Trace: log tool call ---
                    if tracing_enabled:
                        try:
                            log_trace(
                                trace_run_id, agent.name, "tool_call",
                                f"Tool: {tool_name} | Args: {json.dumps(tool_args)[:300]}",
                            )
                        except Exception:
                            pass

                    # --- Approval Gate: check before executing risky tools ---
                    if approval_enabled:
                        try:
                            if needs_approval(tool_name, tool_args, approval_mode):
                                # --- Notifications: approval needed ---
                                try:
                                    from src.core.notifications import send_notification
                                    send_notification(
                                        "approval", agent.name,
                                        f"Needs permission to use tool '{tool_name}'",
                                    )
                                except Exception:
                                    pass
                                approved = request_approval(
                                    agent.name, tool_name, tool_args, channel="cli",
                                )
                                if not approved:
                                    logger.info(
                                        "Tool '%s' denied by approval gate for agent '%s'",
                                        tool_name, agent.name,
                                    )
                                    tool_result = {
                                        "ok": False,
                                        "error": f"Action '{tool_name}' denied by human approval gate",
                                    }
                                    messages.append({
                                        "role": "tool",
                                        "tool_call_id": tool_call.get("id", ""),
                                        "content": json.dumps(tool_result),
                                    })
                                    continue
                        except Exception as approval_err:
                            logger.debug("Approval check failed: %s", approval_err)

                    # --- Security: sanitise tool inputs ---
                    if security_enabled:
                        try:
                            tool_args = sanitize_tool_input(tool_name, tool_args)

                            # File access check for file-related tools
                            if tool_name in ("read_file", "write_file"):
                                file_path = tool_args.get("path", tool_args.get("file_path", ""))
                                if file_path and not check_file_access(file_path):
                                    audit_log("file_access_blocked", agent.name, f"path={file_path}")
                                    tool_result = {"ok": False, "error": "File access denied"}
                                    messages.append({
                                        "role": "tool",
                                        "tool_call_id": tool_call.get("id", ""),
                                        "content": json.dumps(tool_result),
                                    })
                                    continue

                            audit_log("tool_call", agent.name, f"tool={tool_name}")
                        except ValueError as ve:
                            audit_log("tool_input_blocked", agent.name, str(ve))
                            tool_result = {"ok": False, "error": str(ve)}
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.get("id", ""),
                                "content": json.dumps(tool_result),
                            })
                            continue

                    # Execute the tool (with self-healing on failure)
                    tool_result = execute_tool(tool_name, tool_args)

                    # --- Self-Healing: try to recover from tool failure ---
                    if isinstance(tool_result, dict) and not tool_result.get("ok", True):
                        try:
                            from src.core.healing import heal_tool_failure
                            healed = heal_tool_failure(
                                tool_name, tool_args, tool_result.get("error", ""),
                            )
                            if healed.get("ok"):
                                tool_result = healed
                        except Exception:
                            pass  # healing itself failed, keep original result

                    tools_used.append(tool_name)

                    # Track tool call usage
                    if tracking_enabled:
                        track_usage(agent.name, tool_calls=1)
                    if pm_enabled:
                        update_process(process_pid, tool_calls=1)

                    # --- Trace: log tool result ---
                    if tracing_enabled:
                        try:
                            _result_str = json.dumps(tool_result)[:300]
                            log_trace(
                                trace_run_id, agent.name, "tool_result",
                                f"Tool: {tool_name} | Result: {_result_str}",
                            )
                        except Exception:
                            pass

                    # Append tool result to messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.get("id", ""),
                        "content": json.dumps(tool_result),
                    })

            # If we hit max loops, return what we have
            if pm_enabled:
                update_process(process_pid, status="completed")

            # --- Analytics: record max-loop run ---
            _record_analytics(
                agent.name, task, True,
                time.time() - start_time, 0, len(tools_used), "",
            )

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

            # --- Memory: summarize old messages if there are too many ---
            if memory_enabled:
                try:
                    summarize_old_messages(agent.name, keep_recent=20)
                except Exception:
                    pass

    except Exception as e:
        logger.error("Agent '%s' crashed: %s", agent.name, e, exc_info=True)
        # --- Health: record error ---
        if health_enabled:
            try:
                _record_health_error(agent.name)
            except Exception:
                pass
        # --- Trace: log error ---
        if tracing_enabled:
            try:
                log_trace(trace_run_id, agent.name, "error", f"Crash: {e}")
                log_trace(trace_run_id, agent.name, "trace_end", "Trace ended with error")
            except Exception:
                pass
        if pm_enabled:
            update_process(process_pid, status="error", error=str(e))

        # --- Notifications: agent error ---
        try:
            from src.core.notifications import send_notification
            send_notification(
                "error", agent.name,
                f"Agent crashed: {str(e)[:120]}",
            )
        except Exception:
            pass

        # --- Analytics: record crashed run ---
        _record_analytics(
            agent.name, task, False,
            time.time() - start_time, 0, len(tools_used), str(e),
        )

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


def _save_run_knowledge(agent_name: str, task: str, output: str) -> None:
    """Save key findings from an agent run to the knowledge graph.

    Extracts a topic from the task and stores the output summary.

    Args:
        agent_name: The agent that produced the result.
        task: The original task description.
        output: The agent's final output text.
    """
    try:
        from src.core.knowledge import add_knowledge, auto_link

        if not output or len(output.strip()) < 20:
            return

        # Derive topic from first few words of the task
        topic_words = task.strip().split()[:5]
        topic = " ".join(topic_words) if topic_words else "general"

        # Truncate output for storage (keep first 500 chars)
        content = output.strip()[:500]

        add_knowledge(agent_name, topic, content, source=f"run:{task[:80]}")

        # Try to auto-link with existing knowledge
        auto_link(agent_name)
    except Exception as e:
        # Knowledge saving is best-effort — never block agent execution
        logger.debug("Failed to save run knowledge: %s", e)


def _record_analytics(
    agent_name: str,
    task: str,
    success: bool,
    duration: float,
    tokens: int,
    tools: int,
    error: str,
) -> None:
    """Record a completed agent run in the analytics database.

    Best-effort — never blocks agent execution.

    Args:
        agent_name: Name of the agent.
        task: The task description.
        success: Whether the run succeeded.
        duration: Duration in seconds.
        tokens: Estimated tokens used.
        tools: Number of tool calls.
        error: Error message if failed.
    """
    try:
        from src.core.analytics import record_run
        record_run(
            agent_name=agent_name,
            task=task,
            success=success,
            duration=duration,
            tokens=tokens,
            tools=tools,
            cost=0.0,  # Cost estimation can be refined later
            error=error,
        )
    except Exception as e:
        logger.debug("Failed to record analytics: %s", e)
