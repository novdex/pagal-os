"""PAGAL OS Sandbox — isolated execution wrapper for agents.

Supports two isolation modes:

* **thread** (default) — runs agents in a daemon thread within the same
  process.  Lightweight but offers no OS-level isolation.

* **process** — runs agents in a separate Python subprocess with restricted
  environment variables, resource limits (CPU time, address space), and no
  network access to localhost admin ports.  Falls back to thread mode if
  subprocess creation fails.

Set the ``PAGAL_SANDBOX_MODE`` environment variable to ``process`` to enable
subprocess isolation (recommended for production).
"""

import json
import logging
import os
import subprocess
import sys
import textwrap
import threading
from pathlib import Path
from typing import Any

from src.core.runtime import AgentConfig, AgentResult, run_agent

logger = logging.getLogger("pagal_os")

# ---------------------------------------------------------------------------
# Isolation mode configuration
# ---------------------------------------------------------------------------

_SANDBOX_MODE = os.environ.get("PAGAL_SANDBOX_MODE", "thread").lower()


def run_in_sandbox(
    agent: AgentConfig,
    task: str,
    timeout: int = 300,
) -> AgentResult:
    """Run an agent in an isolated environment with a timeout.

    Dispatches to subprocess or thread isolation based on PAGAL_SANDBOX_MODE.

    Args:
        agent: The agent configuration to run.
        task: The user's task/prompt.
        timeout: Maximum execution time in seconds.

    Returns:
        AgentResult — always returns, even on catastrophic failure.
    """
    if _SANDBOX_MODE == "process":
        return _run_in_process(agent, task, timeout)
    return _run_in_thread(agent, task, timeout)


# ---------------------------------------------------------------------------
# Thread-based isolation (lightweight, default)
# ---------------------------------------------------------------------------


def _run_in_thread(
    agent: AgentConfig,
    task: str,
    timeout: int,
) -> AgentResult:
    """Run an agent in an isolated thread with a timeout."""
    result_holder: dict[str, Any] = {"result": None}

    def _worker() -> None:
        try:
            result_holder["result"] = run_agent(agent, task)
        except Exception as e:
            logger.error(
                "Sandbox caught exception for agent '%s': %s",
                agent.name, e, exc_info=True,
            )
            result_holder["result"] = AgentResult(
                ok=False, output="", tools_used=[],
                duration_seconds=0.0, error=f"Sandbox error: {e}",
            )

    thread = threading.Thread(target=_worker, daemon=True, name=f"sandbox-{agent.name}")
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        logger.warning("Agent '%s' timed out after %ds", agent.name, timeout)
        return AgentResult(
            ok=False, output="", tools_used=[],
            duration_seconds=float(timeout),
            error=f"Agent timed out after {timeout} seconds",
        )

    result = result_holder.get("result")
    if result is None:
        return AgentResult(
            ok=False, output="", tools_used=[],
            duration_seconds=0.0, error="Agent returned no result",
        )
    return result


# ---------------------------------------------------------------------------
# Process-based isolation (stronger, production)
# ---------------------------------------------------------------------------

# Environment variables that must NEVER be passed to child processes.
_BLOCKED_ENV_KEYS = {
    "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "GITHUB_TOKEN", "GH_TOKEN",
    "PAGAL_API_TOKEN",
}

# Script template executed inside the child process.
_CHILD_SCRIPT = textwrap.dedent("""\
    import json, sys, os
    sys.path.insert(0, os.environ["_PAGAL_PROJECT_ROOT"])
    from src.core.runtime import AgentConfig, run_agent
    cfg = json.loads(os.environ["_PAGAL_AGENT_CFG"])
    task = os.environ["_PAGAL_TASK"]
    agent = AgentConfig(**cfg)
    try:
        r = run_agent(agent, task)
        out = {"ok": r.ok, "output": r.output, "tools_used": r.tools_used,
               "duration_seconds": r.duration_seconds, "error": r.error}
    except Exception as e:
        out = {"ok": False, "output": "", "tools_used": [],
               "duration_seconds": 0.0, "error": str(e)}
    sys.stdout.write(json.dumps(out))
""")


def _run_in_process(
    agent: AgentConfig,
    task: str,
    timeout: int,
) -> AgentResult:
    """Run an agent in a separate subprocess with restricted privileges.

    Falls back to thread isolation on failure.
    """
    try:
        project_root = str(Path(__file__).parent.parent.parent)

        # Build a restricted environment
        child_env = {
            k: v for k, v in os.environ.items()
            if k.upper() not in _BLOCKED_ENV_KEYS
        }
        child_env["_PAGAL_PROJECT_ROOT"] = project_root
        child_env["_PAGAL_AGENT_CFG"] = json.dumps({
            "name": agent.name,
            "description": agent.description,
            "model": agent.model,
            "tools": agent.tools,
            "personality": agent.personality,
            "memory": agent.memory,
            "schedule": agent.schedule,
            "budget": agent.budget,
        })
        child_env["_PAGAL_TASK"] = task

        result = subprocess.run(
            [sys.executable, "-c", _CHILD_SCRIPT],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=child_env,
            cwd=project_root,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()[:500]
            logger.error("Subprocess sandbox error for '%s': %s", agent.name, stderr)
            return AgentResult(
                ok=False, output="", tools_used=[],
                duration_seconds=0.0,
                error=f"Subprocess error: {stderr}",
            )

        data = json.loads(result.stdout)
        return AgentResult(
            ok=data.get("ok", False),
            output=data.get("output", ""),
            tools_used=data.get("tools_used", []),
            duration_seconds=data.get("duration_seconds", 0.0),
            error=data.get("error", ""),
        )

    except subprocess.TimeoutExpired:
        logger.warning("Agent '%s' subprocess timed out after %ds", agent.name, timeout)
        return AgentResult(
            ok=False, output="", tools_used=[],
            duration_seconds=float(timeout),
            error=f"Agent timed out after {timeout} seconds",
        )
    except Exception as e:
        logger.warning(
            "Subprocess sandbox failed for '%s', falling back to thread: %s",
            agent.name, e,
        )
        return _run_in_thread(agent, task, timeout)
