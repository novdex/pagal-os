"""PAGAL OS Agent-to-Agent Protocol (A2A) — agents talk to each other over HTTP.

Supports both local and remote agent-to-agent communication. An agent on your
machine can call an agent on another machine using simple HTTP POST requests.

Security features:
  - Bearer token authentication (A2A_AUTH_TOKEN)
  - HMAC-SHA256 request signing to prevent tampering
  - Replay protection via timestamp + nonce
  - TLS-first: all outgoing calls default to HTTPS
"""

import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import httpx

logger = logging.getLogger("pagal_os")

# Registry of remote agent endpoints: agent_name -> url
_remote_agents: dict[str, str] = {}

# A2A server instance
_a2a_server: HTTPServer | None = None
_a2a_server_thread: threading.Thread | None = None

# Auth token for verifying incoming requests
_auth_token: str = os.getenv("A2A_AUTH_TOKEN", "")

# HMAC signing secret — shared between A2A peers.
# Set via A2A_SIGNING_SECRET env var; if unset, signing is disabled.
_signing_secret: str = os.getenv("A2A_SIGNING_SECRET", "")

# Replay protection window (seconds)
_REPLAY_WINDOW = 300  # 5 minutes
_seen_nonces: dict[str, float] = {}
_nonce_lock = threading.Lock()


def _sign_payload(payload_bytes: bytes) -> str:
    """Create an HMAC-SHA256 signature for a payload.

    Returns empty string if signing is disabled (no secret configured).
    """
    if not _signing_secret:
        return ""
    return hmac.new(
        _signing_secret.encode(), payload_bytes, hashlib.sha256,
    ).hexdigest()


def _verify_signature(payload_bytes: bytes, signature: str) -> bool:
    """Verify an HMAC-SHA256 signature.

    Returns True if signing is disabled (permissive) or signature is valid.
    """
    if not _signing_secret:
        return True  # Signing not configured — allow
    expected = hmac.new(
        _signing_secret.encode(), payload_bytes, hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def _check_replay(nonce: str, timestamp: float) -> bool:
    """Check if a request is a replay.

    Returns True if the request is fresh, False if it's a replay.
    """
    now = time.time()

    # Reject stale timestamps
    if abs(now - timestamp) > _REPLAY_WINDOW:
        return False

    with _nonce_lock:
        # Prune old nonces
        stale = [k for k, v in _seen_nonces.items() if now - v > _REPLAY_WINDOW]
        for k in stale:
            del _seen_nonces[k]

        # Check for replay
        if nonce in _seen_nonces:
            return False
        _seen_nonces[nonce] = now
        return True


def register_agent_endpoint(agent_name: str, url: str) -> bool:
    """Register a remote agent's URL for A2A communication.

    Args:
        agent_name: The name of the remote agent.
        url: The full URL to reach the agent (e.g. 'http://remote:18791').

    Returns:
        True if registered successfully.
    """
    try:
        _remote_agents[agent_name] = url.rstrip("/")
        logger.info("Registered remote agent '%s' at %s", agent_name, url)
        return True
    except Exception as e:
        logger.error("Failed to register agent endpoint '%s': %s", agent_name, e)
        return False


def unregister_agent_endpoint(agent_name: str) -> bool:
    """Remove a remote agent registration.

    Args:
        agent_name: The agent to unregister.

    Returns:
        True if the agent was registered and removed, False otherwise.
    """
    if agent_name in _remote_agents:
        del _remote_agents[agent_name]
        logger.info("Unregistered remote agent '%s'", agent_name)
        return True
    return False


def list_remote_agents() -> list[dict[str, str]]:
    """List all registered remote agent endpoints.

    Returns:
        List of dicts with 'agent_name' and 'url' keys.
    """
    return [
        {"agent_name": name, "url": url}
        for name, url in _remote_agents.items()
    ]


def call_remote_agent(
    agent_name: str,
    task: str,
    timeout: int = 120,
) -> dict[str, Any]:
    """Send a task to a remote agent via HTTP POST.

    Args:
        agent_name: The name of the remote agent to call.
        task: The task description to send.
        timeout: Request timeout in seconds.

    Returns:
        Dict with 'ok', 'result', 'agent', 'duration_seconds' keys.
    """
    url = _remote_agents.get(agent_name)
    if not url:
        return {
            "ok": False,
            "error": f"Remote agent '{agent_name}' not registered. "
                     f"Known agents: {list(_remote_agents.keys())}",
        }

    try:
        import platform
        caller_id = f"pagal-os@{platform.node()}"
        nonce = secrets.token_hex(16)

        payload = {
            "agent": agent_name,
            "task": task,
            "caller": caller_id,
            "auth_token": _auth_token,
            "nonce": nonce,
            "timestamp": time.time(),
        }

        payload_bytes = json.dumps(payload, sort_keys=True).encode()
        signature = _sign_payload(payload_bytes)

        start_time = time.time()

        # Prefer HTTPS for remote communication
        target_url = f"{url}/a2a/run"
        if target_url.startswith("http://") and not any(
            h in url for h in ("localhost", "127.0.0.1", "0.0.0.0")
        ):
            target_url = target_url.replace("http://", "https://", 1)
            logger.debug("A2A: upgraded to HTTPS for remote call to %s", agent_name)

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if signature:
            headers["X-A2A-Signature"] = signature
        if _auth_token:
            headers["Authorization"] = f"Bearer {_auth_token}"

        with httpx.Client(timeout=timeout) as client:
            response = client.post(target_url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        duration = time.time() - start_time

        logger.info(
            "A2A call to '%s' completed in %.1fs",
            agent_name, duration,
        )

        return {
            "ok": data.get("ok", False),
            "result": data.get("result", ""),
            "agent": data.get("agent", agent_name),
            "duration_seconds": data.get("duration_seconds", duration),
        }

    except httpx.TimeoutException:
        logger.error("A2A call to '%s' timed out after %ds", agent_name, timeout)
        return {"ok": False, "error": f"Timeout calling remote agent '{agent_name}'"}
    except httpx.HTTPStatusError as e:
        logger.error("A2A HTTP error calling '%s': %s", agent_name, e)
        return {"ok": False, "error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        logger.error("A2A call to '%s' failed: %s", agent_name, e)
        return {"ok": False, "error": str(e)}


# ============================================================================
# A2A Server — accept incoming agent calls
# ============================================================================


class _A2ARequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for incoming agent-to-agent calls."""

    def log_message(self, format: str, *args: Any) -> None:
        """Use our logger instead of stderr."""
        logger.debug("A2A Server: %s", format % args)

    def do_POST(self) -> None:
        """Handle incoming POST /a2a/run requests."""
        try:
            if self.path != "/a2a/run":
                self._send_json(404, {"ok": False, "error": "Not found"})
                return

            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)

            # Verify HMAC signature if signing is enabled
            signature = self.headers.get("X-A2A-Signature", "")
            if _signing_secret and not _verify_signature(body, signature):
                logger.warning("A2A: invalid signature on incoming request")
                self._send_json(403, {"ok": False, "error": "Invalid signature"})
                return

            # Verify bearer token from header (preferred) or body
            auth_header = self.headers.get("Authorization", "")
            if _auth_token and auth_header:
                if not auth_header.startswith("Bearer ") or not hmac.compare_digest(
                    auth_header[7:], _auth_token
                ):
                    self._send_json(403, {"ok": False, "error": "Authentication failed"})
                    return

            request = json.loads(body.decode("utf-8"))

            response = handle_a2a_request(request)

            status_code = 200 if response.get("ok") else 400
            self._send_json(status_code, response)

        except Exception as e:
            logger.error("A2A server request error: %s", e)
            self._send_json(500, {"ok": False, "error": str(e)})

    def do_GET(self) -> None:
        """Handle GET /a2a/health for health checks."""
        if self.path == "/a2a/health":
            self._send_json(200, {"ok": True, "service": "pagal-os-a2a"})
        else:
            self._send_json(404, {"ok": False, "error": "Not found"})

    def _send_json(self, status: int, data: dict[str, Any]) -> None:
        """Send a JSON response.

        Args:
            status: HTTP status code.
            data: Response data to serialize as JSON.
        """
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))


def start_a2a_server(port: int = 18791) -> bool:
    """Start the A2A HTTP server that accepts incoming agent calls.

    Args:
        port: TCP port to listen on.

    Returns:
        True if server started, False if already running or failed.
    """
    global _a2a_server, _a2a_server_thread

    if _a2a_server is not None:
        logger.warning("A2A server is already running")
        return False

    try:
        _a2a_server = HTTPServer(("0.0.0.0", port), _A2ARequestHandler)

        def _serve() -> None:
            logger.info("A2A server listening on port %d", port)
            _a2a_server.serve_forever()

        _a2a_server_thread = threading.Thread(target=_serve, daemon=True, name="a2a-server")
        _a2a_server_thread.start()

        logger.info("A2A server started on port %d", port)
        return True

    except Exception as e:
        logger.error("Failed to start A2A server: %s", e)
        _a2a_server = None
        return False


def stop_a2a_server() -> None:
    """Stop the running A2A server."""
    global _a2a_server, _a2a_server_thread

    if _a2a_server:
        _a2a_server.shutdown()
        _a2a_server = None
        _a2a_server_thread = None
        logger.info("A2A server stopped")


def handle_a2a_request(request: dict[str, Any]) -> dict[str, Any]:
    """Process an incoming A2A request: run a local agent and return the result.

    Verifies the auth token, loads the requested agent, runs the task, and
    returns the result.

    Args:
        request: Dict with 'agent', 'task', 'caller', 'auth_token' keys.

    Returns:
        Dict with 'ok', 'result', 'agent', 'duration_seconds' keys.
    """
    try:
        # Verify auth token if one is configured
        if _auth_token:
            incoming_token = request.get("auth_token", "")
            if not hmac.compare_digest(incoming_token, _auth_token):
                logger.warning(
                    "A2A auth failure from caller '%s'",
                    request.get("caller", "unknown"),
                )
                return {"ok": False, "error": "Authentication failed"}

        # Replay protection
        nonce = request.get("nonce", "")
        timestamp = request.get("timestamp", 0.0)
        if nonce and timestamp:
            if not _check_replay(nonce, float(timestamp)):
                logger.warning("A2A replay attack blocked from '%s'", request.get("caller", "unknown"))
                return {"ok": False, "error": "Replay detected or stale request"}

        agent_name = request.get("agent", "")
        task = request.get("task", "")
        caller = request.get("caller", "unknown")

        if not agent_name or not task:
            return {"ok": False, "error": "Missing 'agent' or 'task' in request"}

        logger.info(
            "A2A request from '%s': agent='%s', task='%s'",
            caller, agent_name, task[:100],
        )

        # Run the local agent
        start_time = time.time()

        from src.core.runtime import load_agent, run_agent

        agent = load_agent(agent_name)
        result = run_agent(agent, task)
        duration = time.time() - start_time

        return {
            "ok": result.ok,
            "result": result.output if result.ok else result.error,
            "agent": agent_name,
            "duration_seconds": round(duration, 2),
        }

    except FileNotFoundError:
        return {"ok": False, "error": f"Agent '{request.get('agent', '')}' not found"}
    except Exception as e:
        logger.error("A2A request handling failed: %s", e)
        return {"ok": False, "error": str(e)}
