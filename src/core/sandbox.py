"""PAGAL OS Sandbox — isolated execution wrapper for agents."""

import logging
import threading
from typing import Any

from src.core.runtime import AgentConfig, AgentResult, run_agent

logger = logging.getLogger("pagal_os")


def run_in_sandbox(
    agent: AgentConfig,
    task: str,
    timeout: int = 300,
) -> AgentResult:
    """Run an agent in an isolated thread with a timeout.

    Catches ALL exceptions so the main process never crashes.

    Args:
        agent: The agent configuration to run.
        task: The user's task/prompt.
        timeout: Maximum execution time in seconds.

    Returns:
        AgentResult — always returns, even on catastrophic failure.
    """
    result_holder: dict[str, Any] = {"result": None}

    def _worker() -> None:
        """Execute the agent and store the result."""
        try:
            result_holder["result"] = run_agent(agent, task)
        except Exception as e:
            logger.error(
                "Sandbox caught exception for agent '%s': %s",
                agent.name, e, exc_info=True,
            )
            result_holder["result"] = AgentResult(
                ok=False,
                output="",
                tools_used=[],
                duration_seconds=0.0,
                error=f"Sandbox error: {e}",
            )

    thread = threading.Thread(target=_worker, daemon=True, name=f"sandbox-{agent.name}")
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        logger.warning(
            "Agent '%s' timed out after %ds",
            agent.name, timeout,
        )
        return AgentResult(
            ok=False,
            output="",
            tools_used=[],
            duration_seconds=float(timeout),
            error=f"Agent timed out after {timeout} seconds",
        )

    result = result_holder.get("result")
    if result is None:
        return AgentResult(
            ok=False,
            output="",
            tools_used=[],
            duration_seconds=0.0,
            error="Agent returned no result",
        )

    return result
