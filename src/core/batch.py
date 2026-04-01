"""Batch Processing — run agents on multiple items with progress tracking.

Queue-based batch processing that runs an agent on many items sequentially
or in parallel, with real-time progress tracking and persistence.
"""

import json
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("pagal_os")

# Persistent storage
_BATCHES_FILE = Path.home() / ".pagal-os" / "batches.json"

# In-memory batch store: batch_id -> BatchJob
_batches: dict[str, "BatchJob"] = {}


@dataclass
class BatchJob:
    """A batch processing job that runs an agent on multiple items.

    Attributes:
        id: Unique batch job identifier.
        agent_name: Name of the agent to run on each item.
        items: List of task strings to process.
        status: Current status ('queued', 'running', 'completed', 'failed', 'cancelled').
        progress: Percentage complete (0-100).
        results: List of result dicts for each processed item.
        started_at: Unix timestamp when the batch started.
        completed_at: Unix timestamp when the batch finished (0 if still running).
    """

    id: str
    agent_name: str
    items: list[str]
    status: str = "queued"  # queued, running, completed, failed, cancelled
    progress: float = 0.0
    results: list[dict[str, Any]] = field(default_factory=list)
    started_at: float = 0.0
    completed_at: float = 0.0


def _save_batches() -> None:
    """Persist all batch jobs to disk at ~/.pagal-os/batches.json."""
    try:
        _BATCHES_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for batch_id, batch in _batches.items():
            data[batch_id] = {
                "id": batch.id,
                "agent_name": batch.agent_name,
                "items": batch.items,
                "status": batch.status,
                "progress": batch.progress,
                "results": batch.results,
                "started_at": batch.started_at,
                "completed_at": batch.completed_at,
            }
        _BATCHES_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        logger.error("Failed to save batches: %s", e)


def _load_batches() -> None:
    """Load batch jobs from disk into memory."""
    global _batches
    try:
        if _BATCHES_FILE.exists():
            data = json.loads(_BATCHES_FILE.read_text(encoding="utf-8"))
            for batch_id, batch_data in data.items():
                _batches[batch_id] = BatchJob(
                    id=batch_data["id"],
                    agent_name=batch_data["agent_name"],
                    items=batch_data["items"],
                    status=batch_data["status"],
                    progress=batch_data["progress"],
                    results=batch_data["results"],
                    started_at=batch_data.get("started_at", 0.0),
                    completed_at=batch_data.get("completed_at", 0.0),
                )
    except Exception as e:
        logger.error("Failed to load batches: %s", e)


# Load on import
_load_batches()


def create_batch(agent_name: str, items: list[str]) -> str:
    """Create a new batch job for processing multiple items with an agent.

    Args:
        agent_name: Name of the agent to run on each item.
        items: List of task strings (each is a separate invocation).

    Returns:
        The batch job ID string.
    """
    batch_id = str(uuid.uuid4())[:8]
    batch = BatchJob(
        id=batch_id,
        agent_name=agent_name,
        items=items,
        status="queued",
    )
    _batches[batch_id] = batch
    _save_batches()
    logger.info("Created batch '%s': %d items for agent '%s'", batch_id, len(items), agent_name)
    return batch_id


def run_batch(batch_id: str) -> dict[str, Any]:
    """Run a batch job sequentially, processing items one at a time.

    Updates progress after each item completes.

    Args:
        batch_id: The batch job ID to run.

    Returns:
        Dict with 'ok', 'batch_id', 'completed', 'failed', and 'results'.
    """
    try:
        batch = _batches.get(batch_id)
        if not batch:
            return {"ok": False, "error": f"Batch '{batch_id}' not found"}

        if batch.status == "cancelled":
            return {"ok": False, "error": f"Batch '{batch_id}' was cancelled"}

        from src.core.runtime import load_agent, run_agent

        batch.status = "running"
        batch.started_at = time.time()
        batch.results = []
        _save_batches()

        agent = load_agent(batch.agent_name)
        completed = 0
        failed = 0

        for i, item in enumerate(batch.items):
            # Check if cancelled
            if batch.status == "cancelled":
                break

            try:
                result = run_agent(agent, item)
                batch.results.append({
                    "item_index": i,
                    "task": item,
                    "ok": result.ok,
                    "output": result.output[:1000],  # Cap output size
                    "error": result.error,
                    "duration": result.duration_seconds,
                })
                if result.ok:
                    completed += 1
                else:
                    failed += 1
            except Exception as e:
                batch.results.append({
                    "item_index": i,
                    "task": item,
                    "ok": False,
                    "output": "",
                    "error": str(e),
                    "duration": 0,
                })
                failed += 1

            # Update progress
            batch.progress = ((i + 1) / len(batch.items)) * 100
            _save_batches()

        batch.status = "completed" if batch.status != "cancelled" else "cancelled"
        batch.completed_at = time.time()
        _save_batches()

        return {
            "ok": True,
            "batch_id": batch_id,
            "completed": completed,
            "failed": failed,
            "total": len(batch.items),
            "duration": batch.completed_at - batch.started_at,
        }
    except FileNotFoundError as e:
        if batch_id in _batches:
            _batches[batch_id].status = "failed"
            _save_batches()
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.error("Batch '%s' failed: %s", batch_id, e)
        if batch_id in _batches:
            _batches[batch_id].status = "failed"
            _save_batches()
        return {"ok": False, "error": str(e)}


def run_batch_parallel(batch_id: str, workers: int = 3) -> dict[str, Any]:
    """Run a batch job in parallel using a thread pool.

    Faster than sequential but uses more resources. Each item runs
    in a separate thread.

    Args:
        batch_id: The batch job ID to run.
        workers: Number of parallel workers (default 3).

    Returns:
        Dict with 'ok', 'batch_id', 'completed', 'failed', and 'results'.
    """
    try:
        batch = _batches.get(batch_id)
        if not batch:
            return {"ok": False, "error": f"Batch '{batch_id}' not found"}

        if batch.status == "cancelled":
            return {"ok": False, "error": f"Batch '{batch_id}' was cancelled"}

        from src.core.runtime import load_agent, run_agent

        batch.status = "running"
        batch.started_at = time.time()
        batch.results = [None] * len(batch.items)  # type: ignore[list-item]
        _save_batches()

        agent = load_agent(batch.agent_name)
        completed = 0
        failed = 0
        processed = 0

        def _process_item(index: int, task: str) -> dict[str, Any]:
            """Process a single batch item.

            Args:
                index: Item index in the batch.
                task: The task string.

            Returns:
                Result dict for this item.
            """
            try:
                result = run_agent(agent, task)
                return {
                    "item_index": index,
                    "task": task,
                    "ok": result.ok,
                    "output": result.output[:1000],
                    "error": result.error,
                    "duration": result.duration_seconds,
                }
            except Exception as e:
                return {
                    "item_index": index,
                    "task": task,
                    "ok": False,
                    "output": "",
                    "error": str(e),
                    "duration": 0,
                }

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(_process_item, i, item): i
                for i, item in enumerate(batch.items)
            }

            for future in as_completed(futures):
                if batch.status == "cancelled":
                    break

                result = future.result()
                idx = result["item_index"]
                batch.results[idx] = result  # type: ignore[index]

                if result["ok"]:
                    completed += 1
                else:
                    failed += 1

                processed += 1
                batch.progress = (processed / len(batch.items)) * 100
                _save_batches()

        batch.status = "completed" if batch.status != "cancelled" else "cancelled"
        batch.completed_at = time.time()
        _save_batches()

        return {
            "ok": True,
            "batch_id": batch_id,
            "completed": completed,
            "failed": failed,
            "total": len(batch.items),
            "duration": batch.completed_at - batch.started_at,
            "workers": workers,
        }
    except FileNotFoundError as e:
        if batch_id in _batches:
            _batches[batch_id].status = "failed"
            _save_batches()
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.error("Parallel batch '%s' failed: %s", batch_id, e)
        if batch_id in _batches:
            _batches[batch_id].status = "failed"
            _save_batches()
        return {"ok": False, "error": str(e)}


def get_batch_status(batch_id: str) -> dict[str, Any]:
    """Get the current status and progress of a batch job.

    Args:
        batch_id: The batch job ID.

    Returns:
        Dict with 'ok', 'status', 'progress', 'completed'/'total', and
        estimated time remaining.
    """
    batch = _batches.get(batch_id)
    if not batch:
        return {"ok": False, "error": f"Batch '{batch_id}' not found"}

    completed_items = sum(1 for r in batch.results if r and r.get("ok"))
    failed_items = sum(1 for r in batch.results if r and not r.get("ok"))
    processed = completed_items + failed_items

    # Estimate time remaining
    eta_seconds = 0.0
    if batch.status == "running" and processed > 0 and batch.started_at > 0:
        elapsed = time.time() - batch.started_at
        avg_per_item = elapsed / processed
        remaining = len(batch.items) - processed
        eta_seconds = avg_per_item * remaining

    return {
        "ok": True,
        "batch_id": batch.id,
        "agent_name": batch.agent_name,
        "status": batch.status,
        "progress": round(batch.progress, 1),
        "completed": completed_items,
        "failed": failed_items,
        "total": len(batch.items),
        "eta_seconds": round(eta_seconds, 1),
        "started_at": batch.started_at,
        "completed_at": batch.completed_at,
    }


def list_batches() -> list[dict[str, Any]]:
    """List all batch jobs with their current status.

    Returns:
        List of batch status dicts, most recent first.
    """
    result = []
    for batch in _batches.values():
        result.append({
            "id": batch.id,
            "agent_name": batch.agent_name,
            "status": batch.status,
            "progress": round(batch.progress, 1),
            "items_count": len(batch.items),
            "started_at": batch.started_at,
            "completed_at": batch.completed_at,
        })
    # Sort by started_at descending (most recent first)
    result.sort(key=lambda x: x["started_at"], reverse=True)
    return result


def cancel_batch(batch_id: str) -> bool:
    """Cancel a running or queued batch job.

    Args:
        batch_id: The batch job ID to cancel.

    Returns:
        True if the batch was cancelled, False if not found or already completed.
    """
    batch = _batches.get(batch_id)
    if not batch:
        return False

    if batch.status in ("completed", "cancelled"):
        return False

    batch.status = "cancelled"
    batch.completed_at = time.time()
    _save_batches()
    logger.info("Batch '%s' cancelled", batch_id)
    return True
