"""WebSocket streaming — real-time agent execution visible to users.

Provides a WebSocket endpoint where clients connect, send a task, and
receive a stream of events as the agent works:

  {"event": "started",    "agent": "research_assistant"}
  {"event": "thinking",   "content": "Let me search for that..."}
  {"event": "tool_call",  "tool": "search_web", "args": {"query": "AI news"}}
  {"event": "tool_result","tool": "search_web", "ok": true, "preview": "Found 5 results..."}
  {"event": "token",      "content": "Here"}          # streamed token
  {"event": "token",      "content": " are the"}
  {"event": "completed",  "output": "Here are the top AI stories...", "duration": 3.2}
  {"event": "error",      "message": "Something went wrong"}

Usage from JavaScript:
    const ws = new WebSocket('ws://localhost:3000/ws/agent/run');
    ws.onopen = () => ws.send(JSON.stringify({agent: "research_assistant", task: "find AI news"}));
    ws.onmessage = (e) => { const data = JSON.parse(e.data); console.log(data); };
"""

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("pagal_os")

router = APIRouter()


class StreamCallback:
    """Callback that pushes events to a WebSocket as the agent runs."""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.loop = asyncio.get_event_loop()
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def send(self, event: dict[str, Any]) -> None:
        """Send an event to the WebSocket client."""
        try:
            await self.ws.send_json(event)
        except Exception:
            pass

    def emit(self, event: dict[str, Any]) -> None:
        """Thread-safe emit — called from sync agent runtime."""
        try:
            self.loop.call_soon_threadsafe(self._queue.put_nowait, event)
        except Exception:
            pass


async def _run_agent_streaming(ws: WebSocket, agent_name: str, task: str) -> None:
    """Run an agent and stream events to the WebSocket."""
    import threading

    callback = StreamCallback(ws)
    result_holder: dict[str, Any] = {}

    await callback.send({"event": "started", "agent": agent_name, "task": task})

    def _execute() -> None:
        """Run the agent in a background thread."""
        try:
            from src.core.runtime import load_agent, run_agent

            agent = load_agent(agent_name)

            callback.emit({"event": "thinking", "content": f"Running {agent_name}..."})

            result = run_agent(agent, task)

            result_holder["result"] = {
                "ok": result.ok,
                "output": result.output,
                "tools_used": result.tools_used,
                "duration_seconds": result.duration_seconds,
                "error": result.error,
            }

        except FileNotFoundError:
            result_holder["result"] = {
                "ok": False, "output": "", "tools_used": [],
                "duration_seconds": 0, "error": f"Agent '{agent_name}' not found",
            }
        except Exception as e:
            result_holder["result"] = {
                "ok": False, "output": "", "tools_used": [],
                "duration_seconds": 0, "error": str(e),
            }

    # Run agent in background thread
    thread = threading.Thread(target=_execute, daemon=True)
    thread.start()

    # Stream events from queue while agent runs
    while thread.is_alive() or not callback._queue.empty():
        try:
            event = await asyncio.wait_for(callback._queue.get(), timeout=0.5)
            await callback.send(event)
        except asyncio.TimeoutError:
            # Send heartbeat to keep connection alive
            if thread.is_alive():
                await callback.send({"event": "heartbeat"})

    # Send final result
    result = result_holder.get("result", {})
    if result.get("ok"):
        await callback.send({
            "event": "completed",
            "output": result.get("output", ""),
            "tools_used": result.get("tools_used", []),
            "duration": result.get("duration_seconds", 0),
        })
    else:
        await callback.send({
            "event": "error",
            "message": result.get("error", "Unknown error"),
        })


@router.websocket("/ws/agent/run")
async def ws_agent_run(ws: WebSocket) -> None:
    """WebSocket endpoint for streaming agent execution.

    Client sends: {"agent": "name", "task": "do something"}
    Server streams: events as the agent works, final result on completion.
    """
    await ws.accept()

    try:
        # Wait for initial message with agent name and task
        data = await ws.receive_json()
        agent_name = data.get("agent", "")
        task = data.get("task", "")

        if not agent_name or not task:
            await ws.send_json({"event": "error", "message": "Missing 'agent' or 'task'"})
            await ws.close()
            return

        # Validate agent name
        from src.core.validators import validate_agent_name
        valid, err = validate_agent_name(agent_name)
        if not valid:
            await ws.send_json({"event": "error", "message": err})
            await ws.close()
            return

        await _run_agent_streaming(ws, agent_name, task)

    except WebSocketDisconnect:
        logger.debug("WebSocket client disconnected")
    except Exception as e:
        logger.error("WebSocket error: %s", e)
        try:
            await ws.send_json({"event": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass
