"""PAGAL OS Process Manager — Linux-style process management for agents.

Tracks all running agents as 'processes' with PIDs, status, resource usage,
and provides ps/kill/restart functionality.
"""

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("pagal_os")

# Global process table: pid -> AgentProcess
_processes: dict[str, "AgentProcess"] = {}
_processes_lock = threading.Lock()

# System start time for uptime calculation
_system_start_time: float = time.time()


@dataclass
class AgentProcess:
    """Represents a running agent process, similar to a Linux process entry.

    Attributes:
        pid: Unique process ID (short UUID).
        agent_name: Name of the agent.
        task: The task being executed.
        status: One of 'running', 'idle', 'completed', 'error', 'killed'.
        started_at: Unix timestamp of when the process started.
        finished_at: Unix timestamp of completion (0 if still running).
        cpu_time: Estimated CPU time in seconds.
        memory_mb: Estimated memory usage in MB.
        tokens_used: Total tokens consumed by this process.
        tool_calls: Number of tool calls made.
        priority: Process priority (1-10, higher = more important).
        thread: The threading.Thread running this agent (not serialized).
        error: Error message if the process failed.
    """

    pid: str
    agent_name: str
    task: str = ""
    status: str = "idle"
    started_at: float = 0.0
    finished_at: float = 0.0
    cpu_time: float = 0.0
    memory_mb: float = 0.0
    tokens_used: int = 0
    tool_calls: int = 0
    priority: int = 5
    thread: threading.Thread | None = field(default=None, repr=False)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict (excludes thread).

        Returns:
            Dict with all process info except the thread reference.
        """
        uptime = 0.0
        if self.started_at > 0:
            end = self.finished_at if self.finished_at > 0 else time.time()
            uptime = round(end - self.started_at, 1)

        return {
            "pid": self.pid,
            "agent_name": self.agent_name,
            "task": self.task[:100],
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "uptime_seconds": uptime,
            "cpu_time": round(self.cpu_time, 2),
            "memory_mb": round(self.memory_mb, 1),
            "tokens_used": self.tokens_used,
            "tool_calls": self.tool_calls,
            "priority": self.priority,
            "error": self.error,
        }


def register_process(
    agent_name: str,
    task: str = "",
    thread: threading.Thread | None = None,
) -> str:
    """Register a new agent process in the process table.

    Called when `run_agent` starts. Returns a PID that can be used to track,
    kill, or query the process.

    Args:
        agent_name: The name of the agent being run.
        task: The task string being executed.
        thread: Optional thread reference for kill/monitoring.

    Returns:
        The assigned process ID (PID).
    """
    pid = uuid.uuid4().hex[:8]

    process = AgentProcess(
        pid=pid,
        agent_name=agent_name,
        task=task,
        status="running",
        started_at=time.time(),
        thread=thread,
    )

    with _processes_lock:
        _processes[pid] = process

    logger.info("Registered process %s for agent '%s'", pid, agent_name)
    return pid


def update_process(
    pid: str,
    status: str | None = None,
    tokens: int = 0,
    tool_calls: int = 0,
    error: str = "",
) -> None:
    """Update an existing process with new metrics.

    Args:
        pid: The process ID to update.
        status: New status (if changing).
        tokens: Additional tokens to add to the count.
        tool_calls: Additional tool calls to add.
        error: Error message (if status is 'error').
    """
    with _processes_lock:
        proc = _processes.get(pid)
        if not proc:
            return

        if status:
            proc.status = status
            if status in ("completed", "error", "killed"):
                proc.finished_at = time.time()

        if tokens > 0:
            proc.tokens_used += tokens
        if tool_calls > 0:
            proc.tool_calls += tool_calls
        if error:
            proc.error = error

        # Estimate CPU time based on uptime
        if proc.started_at > 0 and proc.status == "running":
            proc.cpu_time = time.time() - proc.started_at

        # Rough memory estimate: ~0.5MB base + 0.001MB per token
        proc.memory_mb = 0.5 + (proc.tokens_used * 0.001)


def list_processes() -> list[dict[str, Any]]:
    """List all agent processes, like Linux `ps aux`.

    Also cleans up processes whose threads have died.

    Returns:
        List of process info dicts sorted by started_at (newest first).
    """
    with _processes_lock:
        # Clean up dead threads
        for pid, proc in list(_processes.items()):
            if proc.thread and not proc.thread.is_alive() and proc.status == "running":
                proc.status = "completed"
                proc.finished_at = time.time()

        result = [proc.to_dict() for proc in _processes.values()]

    return sorted(result, key=lambda p: p.get("started_at", 0), reverse=True)


def get_process(pid: str) -> dict[str, Any] | None:
    """Get detailed info for a single process.

    Args:
        pid: The process ID.

    Returns:
        Process info dict, or None if not found.
    """
    with _processes_lock:
        proc = _processes.get(pid)
        if proc:
            return proc.to_dict()
    return None


def kill_process(pid: str) -> bool:
    """Force-stop an agent process.

    Note: Python threads cannot be forcibly killed. This sets the status to
    'killed' and removes the process from tracking. The thread will finish
    naturally.

    Args:
        pid: The process ID to kill.

    Returns:
        True if the process was found and marked killed, False otherwise.
    """
    with _processes_lock:
        proc = _processes.get(pid)
        if not proc:
            logger.warning("Process %s not found for kill", pid)
            return False

        proc.status = "killed"
        proc.finished_at = time.time()
        logger.info("Killed process %s (agent '%s')", pid, proc.agent_name)
        return True


def restart_process(pid: str) -> str | None:
    """Kill a process and restart it with the same agent and task.

    Args:
        pid: The process ID to restart.

    Returns:
        The new PID if restarted, or None if the original wasn't found.
    """
    with _processes_lock:
        proc = _processes.get(pid)
        if not proc:
            return None

        agent_name = proc.agent_name
        task = proc.task

        # Kill old process
        proc.status = "killed"
        proc.finished_at = time.time()

    # Start a new process (the caller should use run_agent_async)
    new_pid = register_process(agent_name, task)
    logger.info(
        "Restarted process %s as %s (agent '%s')",
        pid, new_pid, agent_name,
    )
    return new_pid


def get_process_stats(pid: str) -> dict[str, Any]:
    """Get detailed statistics for a single process.

    Args:
        pid: The process ID.

    Returns:
        Dict with detailed metrics, or error if not found.
    """
    with _processes_lock:
        proc = _processes.get(pid)
        if not proc:
            return {"ok": False, "error": f"Process {pid} not found"}

        info = proc.to_dict()
        info["ok"] = True
        info["thread_alive"] = proc.thread.is_alive() if proc.thread else False
        return info


def set_priority(pid: str, priority: int) -> bool:
    """Set the priority of an agent process.

    Args:
        pid: The process ID.
        priority: Priority level from 1 (lowest) to 10 (highest).

    Returns:
        True if priority was set, False if process not found.
    """
    clamped = max(1, min(10, priority))

    with _processes_lock:
        proc = _processes.get(pid)
        if not proc:
            return False
        proc.priority = clamped
        logger.info("Set priority of process %s to %d", pid, clamped)
        return True


def get_system_stats() -> dict[str, Any]:
    """Get overall system statistics across all processes.

    Returns:
        Dict with total_processes, running, total_tokens, uptime, etc.
    """
    with _processes_lock:
        all_procs = list(_processes.values())

    total = len(all_procs)
    running = sum(1 for p in all_procs if p.status == "running")
    completed = sum(1 for p in all_procs if p.status == "completed")
    errored = sum(1 for p in all_procs if p.status == "error")
    killed = sum(1 for p in all_procs if p.status == "killed")
    total_tokens = sum(p.tokens_used for p in all_procs)
    total_tool_calls = sum(p.tool_calls for p in all_procs)
    total_memory = sum(p.memory_mb for p in all_procs)

    uptime = time.time() - _system_start_time

    return {
        "total_processes": total,
        "running": running,
        "completed": completed,
        "errored": errored,
        "killed": killed,
        "total_tokens": total_tokens,
        "total_tool_calls": total_tool_calls,
        "total_memory_mb": round(total_memory, 1),
        "uptime_seconds": round(uptime, 1),
    }


def cleanup_old_processes(max_age_seconds: int = 3600) -> int:
    """Remove completed/killed processes older than max_age.

    Args:
        max_age_seconds: Remove processes finished more than this many seconds ago.

    Returns:
        Number of processes cleaned up.
    """
    cutoff = time.time() - max_age_seconds
    removed = 0

    with _processes_lock:
        to_remove = [
            pid for pid, proc in _processes.items()
            if proc.status in ("completed", "error", "killed")
            and proc.finished_at > 0
            and proc.finished_at < cutoff
        ]
        for pid in to_remove:
            del _processes[pid]
            removed += 1

    if removed:
        logger.info("Cleaned up %d old processes", removed)
    return removed
