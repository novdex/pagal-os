"""Autonomous Goal Pursuit -- agents work toward goals over time.

Give an agent a long-term goal. The system uses an LLM to break it into
sub-tasks, then works on them over days, tracking progress in SQLite.
"""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from src.core.llm import call_llm

logger = logging.getLogger("pagal_os")


def _db_path() -> Path:
    """Return the path to the goals SQLite database.

    Returns:
        Path to ~/.pagal-os/pagal.db.
    """
    db_dir = Path.home() / ".pagal-os"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "pagal.db"


def _get_conn() -> sqlite3.Connection:
    """Open a connection and ensure the agent_goals table exists.

    Delegates to the central database module when available, falling
    back to a local connection if not.

    Returns:
        sqlite3.Connection with agent_goals table ready.
    """
    _default = Path.home() / ".pagal-os" / "pagal.db"
    db = _db_path()
    conn = None
    if db == _default:
        try:
            from src.core.database import get_connection
            conn = get_connection()
        except Exception:
            pass
    if conn is None:
        conn = sqlite3.connect(str(db))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agent_goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_name TEXT NOT NULL,
            goal TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            progress_pct INTEGER DEFAULT 0,
            sub_tasks TEXT DEFAULT '[]',
            completed_tasks TEXT DEFAULT '[]',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_worked_at TIMESTAMP,
            notes TEXT DEFAULT ''
        )
    """)
    conn.commit()
    return conn


def set_goal(agent_name: str, goal_text: str) -> int:
    """Create a new goal and break it into sub-tasks using an LLM.

    The LLM is prompted to break the goal into 5-10 actionable sub-tasks.
    Each sub-task is stored as a JSON list in the database.

    Args:
        agent_name: Name of the agent assigned to this goal.
        goal_text: The high-level goal description.

    Returns:
        The goal ID (integer) of the newly created goal.

    Raises:
        RuntimeError: If the LLM fails to generate sub-tasks.
    """
    try:
        # Use LLM to break goal into sub-tasks
        prompt = (
            f"Break this goal into 5-10 specific, actionable sub-tasks:\n"
            f'Goal: "{goal_text}"\n\n'
            f"Return ONLY a valid JSON array of strings, no explanation:\n"
            f'["sub-task 1", "sub-task 2", ...]'
        )

        messages = [
            {"role": "system", "content": "You are a project planner. Return only valid JSON arrays."},
            {"role": "user", "content": prompt},
        ]

        from src.core.config import get_config
        config = get_config()

        result = call_llm(messages=messages, model=config.default_model, timeout=30)

        if result["ok"]:
            content = result["content"].strip()
            # Strip markdown code fences if present
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
                content = content.strip()
            sub_tasks = json.loads(content)
            if not isinstance(sub_tasks, list):
                sub_tasks = [str(sub_tasks)]
        else:
            # Fallback: create basic sub-tasks
            sub_tasks = [
                f"Research: {goal_text}",
                f"Plan approach for: {goal_text}",
                f"Execute first step of: {goal_text}",
                f"Review progress on: {goal_text}",
                f"Complete: {goal_text}",
            ]

        conn = _get_conn()
        try:
            cursor = conn.execute(
                "INSERT INTO agent_goals (agent_name, goal, sub_tasks) VALUES (?, ?, ?)",
                (agent_name, goal_text, json.dumps(sub_tasks)),
            )
            goal_id = cursor.lastrowid
            conn.commit()
        finally:
            conn.close()

        logger.info("Goal #%d set for '%s': %s (%d sub-tasks)", goal_id, agent_name, goal_text[:60], len(sub_tasks))
        return goal_id

    except json.JSONDecodeError as e:
        logger.error("Failed to parse LLM sub-tasks: %s", e)
        # Still create the goal with fallback sub-tasks
        sub_tasks = [f"Work on: {goal_text}"]
        conn = _get_conn()
        try:
            cursor = conn.execute(
                "INSERT INTO agent_goals (agent_name, goal, sub_tasks) VALUES (?, ?, ?)",
                (agent_name, goal_text, json.dumps(sub_tasks)),
            )
            goal_id = cursor.lastrowid
            conn.commit()
        finally:
            conn.close()
        return goal_id

    except Exception as e:
        logger.error("Failed to set goal for '%s': %s", agent_name, e)
        raise RuntimeError(f"Failed to set goal: {e}") from e


def work_on_goal(goal_id: int) -> dict[str, Any]:
    """Pick the next incomplete sub-task and run the agent on it.

    Loads the goal, finds the first sub-task not yet completed,
    runs the assigned agent, and updates the progress.

    Args:
        goal_id: The database ID of the goal to work on.

    Returns:
        Dict with 'ok', 'sub_task', 'result', and updated 'progress_pct'.
    """
    try:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT agent_name, goal, sub_tasks, completed_tasks, status FROM agent_goals WHERE id = ?",
                (goal_id,),
            ).fetchone()
        finally:
            conn.close()

        if not row:
            return {"ok": False, "error": f"Goal #{goal_id} not found"}

        agent_name, goal, sub_tasks_json, completed_json, status = row

        if status != "active":
            return {"ok": False, "error": f"Goal #{goal_id} is {status}, not active"}

        sub_tasks = json.loads(sub_tasks_json)
        completed = json.loads(completed_json)

        # Find next incomplete sub-task
        remaining = [t for t in sub_tasks if t not in completed]
        if not remaining:
            # All done
            _update_goal_status(goal_id, "completed", 100)
            return {"ok": True, "sub_task": None, "result": "All sub-tasks completed!", "progress_pct": 100}

        current_task = remaining[0]

        # Run agent on this sub-task
        from src.core.runtime import load_agent, run_agent

        try:
            agent = load_agent(agent_name)
            task_with_context = (
                f"You are working on this goal: {goal}\n"
                f"Current sub-task: {current_task}\n"
                f"Previously completed: {', '.join(completed[-3:]) if completed else 'none'}\n"
                f"Please complete this sub-task."
            )
            result = run_agent(agent, task_with_context)

            if result.ok:
                completed.append(current_task)
                progress = int((len(completed) / len(sub_tasks)) * 100)
                _update_goal_progress(goal_id, completed, progress)

                if progress >= 100:
                    _update_goal_status(goal_id, "completed", 100)

                return {
                    "ok": True,
                    "sub_task": current_task,
                    "result": result.output[:500],
                    "progress_pct": progress,
                }
            else:
                return {
                    "ok": False,
                    "sub_task": current_task,
                    "result": "",
                    "error": result.error,
                    "progress_pct": int((len(completed) / len(sub_tasks)) * 100),
                }
        except FileNotFoundError:
            return {"ok": False, "error": f"Agent '{agent_name}' not found"}

    except Exception as e:
        logger.error("Failed to work on goal #%d: %s", goal_id, e)
        return {"ok": False, "error": str(e)}


def get_goal_status(goal_id: int) -> dict[str, Any]:
    """Get the current status and progress of a goal.

    Args:
        goal_id: The database ID of the goal.

    Returns:
        Dict with goal details, progress, sub-tasks, and completed tasks.
    """
    try:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT id, agent_name, goal, status, progress_pct, sub_tasks, "
                "completed_tasks, created_at, last_worked_at, notes FROM agent_goals WHERE id = ?",
                (goal_id,),
            ).fetchone()
        finally:
            conn.close()

        if not row:
            return {"ok": False, "error": f"Goal #{goal_id} not found"}

        sub_tasks = json.loads(row[5])
        completed = json.loads(row[6])
        remaining = [t for t in sub_tasks if t not in completed]

        return {
            "ok": True,
            "id": row[0],
            "agent_name": row[1],
            "goal": row[2],
            "status": row[3],
            "progress_pct": row[4],
            "sub_tasks": sub_tasks,
            "completed_tasks": completed,
            "remaining_tasks": remaining,
            "created_at": row[7],
            "last_worked_at": row[8],
            "notes": row[9],
        }
    except Exception as e:
        logger.error("Failed to get goal status #%d: %s", goal_id, e)
        return {"ok": False, "error": str(e)}


def list_goals(agent_name: str | None = None) -> list[dict[str, Any]]:
    """List all goals, optionally filtered by agent.

    Args:
        agent_name: Optional agent name to filter by.

    Returns:
        List of goal summary dicts.
    """
    try:
        conn = _get_conn()
        try:
            if agent_name:
                rows = conn.execute(
                    "SELECT id, agent_name, goal, status, progress_pct, created_at, last_worked_at "
                    "FROM agent_goals WHERE agent_name = ? ORDER BY created_at DESC",
                    (agent_name,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, agent_name, goal, status, progress_pct, created_at, last_worked_at "
                    "FROM agent_goals ORDER BY created_at DESC",
                ).fetchall()
        finally:
            conn.close()

        return [
            {
                "id": r[0],
                "agent_name": r[1],
                "goal": r[2],
                "status": r[3],
                "progress_pct": r[4],
                "created_at": r[5],
                "last_worked_at": r[6],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("Failed to list goals: %s", e)
        return []


def pause_goal(goal_id: int) -> bool:
    """Pause an active goal.

    Args:
        goal_id: The goal ID to pause.

    Returns:
        True if paused, False if not found or not active.
    """
    return _update_goal_status(goal_id, "paused")


def resume_goal(goal_id: int) -> bool:
    """Resume a paused goal.

    Args:
        goal_id: The goal ID to resume.

    Returns:
        True if resumed, False if not found or not paused.
    """
    return _update_goal_status(goal_id, "active")


def auto_work_goals() -> dict[str, Any]:
    """Autonomously work on the highest-priority incomplete goal.

    Called by a scheduled Hand. Picks the oldest active goal and works
    on one sub-task. This is the core of autonomous goal pursuit.

    Returns:
        Dict with 'ok' and result of the work, or a message if no goals.
    """
    try:
        conn = _get_conn()
        try:
            row = conn.execute(
                "SELECT id FROM agent_goals WHERE status = 'active' ORDER BY created_at ASC LIMIT 1",
            ).fetchone()
        finally:
            conn.close()

        if not row:
            return {"ok": True, "message": "No active goals to work on"}

        goal_id = row[0]
        logger.info("Auto-working on goal #%d", goal_id)
        return work_on_goal(goal_id)
    except Exception as e:
        logger.error("auto_work_goals failed: %s", e)
        return {"ok": False, "error": str(e)}


def _update_goal_status(goal_id: int, status: str, progress: int | None = None) -> bool:
    """Update the status of a goal in the database.

    Args:
        goal_id: The goal ID to update.
        status: New status string.
        progress: Optional progress percentage to set.

    Returns:
        True if the row was updated, False otherwise.
    """
    try:
        conn = _get_conn()
        try:
            if progress is not None:
                conn.execute(
                    "UPDATE agent_goals SET status = ?, progress_pct = ?, last_worked_at = ? WHERE id = ?",
                    (status, progress, datetime.now().isoformat(), goal_id),
                )
            else:
                conn.execute(
                    "UPDATE agent_goals SET status = ?, last_worked_at = ? WHERE id = ?",
                    (status, datetime.now().isoformat(), goal_id),
                )
            conn.commit()
            affected = conn.execute("SELECT changes()").fetchone()[0]
        finally:
            conn.close()
        return affected > 0
    except Exception as e:
        logger.error("Failed to update goal #%d status: %s", goal_id, e)
        return False


def _update_goal_progress(goal_id: int, completed: list[str], progress: int) -> None:
    """Update the completed tasks and progress for a goal.

    Args:
        goal_id: The goal ID to update.
        completed: Updated list of completed task strings.
        progress: New progress percentage.
    """
    try:
        conn = _get_conn()
        try:
            conn.execute(
                "UPDATE agent_goals SET completed_tasks = ?, progress_pct = ?, last_worked_at = ? WHERE id = ?",
                (json.dumps(completed), progress, datetime.now().isoformat(), goal_id),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        logger.error("Failed to update goal #%d progress: %s", goal_id, e)
