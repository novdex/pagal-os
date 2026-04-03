"""PAGAL OS MCP Server + Client — Model Context Protocol integration.

PAGAL OS acts as both an MCP server (exposing tools to external clients) and
an MCP client (connecting to external MCP servers to use their tools).
Uses JSON-RPC 2.0 over stdio (client) and TCP (server).
"""

import json
import logging
import os
import platform
import subprocess
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

logger = logging.getLogger("pagal_os")

# Track connected MCP server processes: name -> {process, tools, ...}
_mcp_connections: dict[str, dict[str, Any]] = {}

# Lock for thread-safe access to connections
_connections_lock = threading.Lock()


# ============================================================================
# MCP Client — connect to and call external MCP servers
# ============================================================================



# Allowed MCP server commands — only these executables may be launched.
_MCP_ALLOWED_COMMANDS: set[str] = {
    "npx", "node", "python", "python3", "uvx", "deno",
    "npx.cmd", "node.cmd",  # Windows variants
}

# Environment variable names that must never be passed to MCP subprocesses.
_MCP_BLOCKED_ENV_KEYS: set[str] = {
    "OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
    "AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "GH_TOKEN",
    "SECRET_KEY", "DATABASE_URL",
}


def connect_mcp_server(
    name: str,
    command: str,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
) -> bool:
    """Launch an external MCP server subprocess and initialise via JSON-RPC.

    Starts the server process with stdio transport, sends the 'initialize'
    request, and caches the connection for future tool calls.

    Only commands in the allowlist (_MCP_ALLOWED_COMMANDS) may be executed.

    Args:
        name: A friendly name for this MCP server connection.
        command: The executable to run (e.g. 'npx', 'python').
        args: Command-line arguments for the executable.
        env: Optional environment variables to pass to the subprocess.

    Returns:
        True if connection was established, False otherwise.
    """
    try:
        if args is None:
            args = []

        # --- Validate command against allowlist ---
        base_command = os.path.basename(command)
        if base_command not in _MCP_ALLOWED_COMMANDS and command not in _MCP_ALLOWED_COMMANDS:
            logger.warning(
                "MCP command blocked (not in allowlist): %s", command,
            )
            return False

        # On Windows, npx is actually npx.cmd
        resolved_command = command
        if platform.system() == "Windows" and command in ("npx", "node"):
            cmd_variant = f"{command}.cmd"
            # Check if .cmd variant exists on PATH
            import shutil
            if shutil.which(cmd_variant):
                resolved_command = cmd_variant

        # Merge environment — strip sensitive keys
        full_env = {
            k: v for k, v in os.environ.items()
            if k.upper() not in _MCP_BLOCKED_ENV_KEYS
        }
        if env:
            # Also strip sensitive keys from user-provided env
            for k, v in env.items():
                if k.upper() not in _MCP_BLOCKED_ENV_KEYS:
                    full_env[k] = v

        # Launch subprocess
        process = subprocess.Popen(
            [resolved_command, *args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=full_env,
            bufsize=0,
        )

        # Send initialize request
        init_request = _build_jsonrpc_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "pagal-os", "version": "0.1.0"},
        })

        response = _send_jsonrpc(process, init_request)
        if response is None:
            logger.error("MCP server '%s' did not respond to initialize", name)
            process.terminate()
            return False

        # Send initialized notification
        _send_jsonrpc_notification(process, "notifications/initialized", {})

        # Cache the connection
        with _connections_lock:
            _mcp_connections[name] = {
                "process": process,
                "command": command,
                "args": args,
                "tools": [],
                "connected": True,
            }

        # Fetch available tools
        tools = list_mcp_tools(name)
        with _connections_lock:
            _mcp_connections[name]["tools"] = tools

        logger.info(
            "Connected to MCP server '%s' with %d tools",
            name, len(tools),
        )
        return True

    except Exception as e:
        logger.error("Failed to connect MCP server '%s': %s", name, e)
        return False


def call_mcp_tool(
    server_name: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call a tool on a connected MCP server.

    Args:
        server_name: The name of the connected MCP server.
        tool_name: The tool to call on that server.
        arguments: Arguments to pass to the tool.

    Returns:
        Dict with 'ok' and 'result' or 'error' keys.
    """
    try:
        with _connections_lock:
            conn = _mcp_connections.get(server_name)

        if not conn or not conn.get("connected"):
            return {"ok": False, "error": f"MCP server '{server_name}' not connected"}

        process = conn["process"]
        if process.poll() is not None:
            return {"ok": False, "error": f"MCP server '{server_name}' process has exited"}

        request = _build_jsonrpc_request("tools/call", {
            "name": tool_name,
            "arguments": arguments or {},
        })

        response = _send_jsonrpc(process, request)
        if response is None:
            return {"ok": False, "error": f"No response from MCP server '{server_name}'"}

        if "error" in response:
            return {"ok": False, "error": response["error"].get("message", "Unknown error")}

        result = response.get("result", {})
        # Extract content from MCP response format
        content_parts = result.get("content", [])
        text_parts = [
            part.get("text", "")
            for part in content_parts
            if part.get("type") == "text"
        ]

        return {
            "ok": True,
            "result": "\n".join(text_parts) if text_parts else str(result),
        }

    except Exception as e:
        logger.error("Failed to call MCP tool '%s/%s': %s", server_name, tool_name, e)
        return {"ok": False, "error": str(e)}


def list_mcp_tools(server_name: str) -> list[dict[str, Any]]:
    """List all tools available on a connected MCP server.

    Args:
        server_name: The name of the connected MCP server.

    Returns:
        List of tool dicts with 'name', 'description', 'inputSchema' keys.
    """
    try:
        with _connections_lock:
            conn = _mcp_connections.get(server_name)

        if not conn or not conn.get("connected"):
            logger.warning("MCP server '%s' not connected", server_name)
            return []

        process = conn["process"]
        request = _build_jsonrpc_request("tools/list", {})
        response = _send_jsonrpc(process, request)

        if response is None:
            return []

        result = response.get("result", {})
        tools = result.get("tools", [])
        return tools

    except Exception as e:
        logger.error("Failed to list MCP tools for '%s': %s", server_name, e)
        return []


def disconnect_mcp_server(name: str) -> None:
    """Shutdown a connected MCP server and clean up.

    Args:
        name: The name of the MCP server to disconnect.
    """
    try:
        with _connections_lock:
            conn = _mcp_connections.pop(name, None)

        if conn:
            process = conn.get("process")
            if process and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
            logger.info("Disconnected MCP server '%s'", name)
        else:
            logger.warning("MCP server '%s' was not connected", name)

    except Exception as e:
        logger.error("Failed to disconnect MCP server '%s': %s", name, e)


def list_mcp_connections() -> list[dict[str, Any]]:
    """List all active MCP server connections.

    Returns:
        List of connection info dicts.
    """
    with _connections_lock:
        result = []
        for name, conn in _mcp_connections.items():
            process = conn.get("process")
            alive = process is not None and process.poll() is None
            result.append({
                "name": name,
                "command": conn.get("command", ""),
                "connected": alive,
                "tools_count": len(conn.get("tools", [])),
                "tools": [t.get("name", "") for t in conn.get("tools", [])],
            })
        return result


# ============================================================================
# MCP Server — expose PAGAL tools to external MCP clients
# ============================================================================


_mcp_server_instance: HTTPServer | None = None
_mcp_server_thread: threading.Thread | None = None


class _MCPRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler that implements the MCP server protocol.

    Handles JSON-RPC 2.0 requests for initialize, tools/list, and tools/call.
    """

    def log_message(self, format: str, *args: Any) -> None:
        """Override to use our logger instead of stderr."""
        logger.debug("MCP Server: %s", format % args)

    def do_POST(self) -> None:
        """Handle incoming POST requests with JSON-RPC payloads."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            request = json.loads(body.decode("utf-8"))

            response = handle_mcp_request(request)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode("utf-8"))

        except Exception as e:
            logger.error("MCP server request error: %s", e)
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32603, "message": str(e)},
            }
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(error_response).encode("utf-8"))


def start_mcp_server(port: int = 18790) -> bool:
    """Start the MCP server that exposes PAGAL tools to external clients.

    Args:
        port: TCP port to listen on.

    Returns:
        True if server started, False if already running or failed.
    """
    global _mcp_server_instance, _mcp_server_thread

    if _mcp_server_instance is not None:
        logger.warning("MCP server is already running")
        return False

    try:
        _mcp_server_instance = HTTPServer(("0.0.0.0", port), _MCPRequestHandler)

        def _serve() -> None:
            logger.info("MCP server listening on port %d", port)
            _mcp_server_instance.serve_forever()

        _mcp_server_thread = threading.Thread(target=_serve, daemon=True, name="mcp-server")
        _mcp_server_thread.start()

        logger.info("MCP server started on port %d", port)
        return True

    except Exception as e:
        logger.error("Failed to start MCP server: %s", e)
        _mcp_server_instance = None
        return False


def stop_mcp_server() -> None:
    """Stop the running MCP server."""
    global _mcp_server_instance, _mcp_server_thread

    if _mcp_server_instance:
        _mcp_server_instance.shutdown()
        _mcp_server_instance = None
        _mcp_server_thread = None
        logger.info("MCP server stopped")


def handle_mcp_request(request: dict[str, Any]) -> dict[str, Any]:
    """Process an incoming MCP JSON-RPC request.

    Supports: initialize, tools/list, tools/call.

    Args:
        request: A JSON-RPC 2.0 request dict.

    Returns:
        A JSON-RPC 2.0 response dict.
    """
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    try:
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "pagal-os", "version": "0.1.0"},
                },
            }

        elif method == "tools/list":
            from src.tools.registry import TOOLS

            tools_list = []
            for name, entry in TOOLS.items():
                schema = entry.get("schema", {}).get("function", {})
                tools_list.append({
                    "name": name,
                    "description": schema.get("description", ""),
                    "inputSchema": schema.get("parameters", {}),
                })

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": tools_list},
            }

        elif method == "tools/call":
            from src.tools.registry import execute_tool

            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})

            result = execute_tool(tool_name, tool_args)

            # Format as MCP content
            content_text = json.dumps(result) if isinstance(result, dict) else str(result)
            is_error = isinstance(result, dict) and not result.get("ok", True)

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": content_text}],
                    "isError": is_error,
                },
            }

        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }

    except Exception as e:
        logger.error("MCP request handling failed: %s", e)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32603, "message": str(e)},
        }


# ============================================================================
# Internal helpers for JSON-RPC communication
# ============================================================================


_jsonrpc_id_counter = 0


def _build_jsonrpc_request(method: str, params: dict[str, Any]) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 request.

    Args:
        method: The RPC method name.
        params: Parameters for the method.

    Returns:
        A JSON-RPC 2.0 request dict.
    """
    global _jsonrpc_id_counter
    _jsonrpc_id_counter += 1
    return {
        "jsonrpc": "2.0",
        "id": _jsonrpc_id_counter,
        "method": method,
        "params": params,
    }


def _send_jsonrpc(
    process: subprocess.Popen,
    request: dict[str, Any],
    timeout: float = 30.0,
) -> dict[str, Any] | None:
    """Send a JSON-RPC request to a subprocess via stdin and read the response from stdout.

    Args:
        process: The subprocess with open stdin/stdout.
        request: The JSON-RPC request dict.
        timeout: Read timeout in seconds.

    Returns:
        The JSON-RPC response dict, or None if communication failed.
    """
    try:
        if process.stdin is None or process.stdout is None:
            return None

        # Write request as newline-delimited JSON
        data = json.dumps(request) + "\n"
        process.stdin.write(data.encode("utf-8"))
        process.stdin.flush()

        # Read response line
        import select
        import sys

        # Simple blocking read with a timeout approach
        # For Windows compatibility, we use a thread-based approach
        result_line: str | None = None

        def _read_line() -> None:
            nonlocal result_line
            try:
                line = process.stdout.readline()
                if line:
                    result_line = line.decode("utf-8").strip()
            except Exception:
                pass

        reader = threading.Thread(target=_read_line, daemon=True)
        reader.start()
        reader.join(timeout=timeout)

        if result_line:
            return json.loads(result_line)
        return None

    except Exception as e:
        logger.error("JSON-RPC communication error: %s", e)
        return None


def _send_jsonrpc_notification(
    process: subprocess.Popen,
    method: str,
    params: dict[str, Any],
) -> None:
    """Send a JSON-RPC 2.0 notification (no response expected).

    Args:
        process: The subprocess to send to.
        method: The notification method name.
        params: Parameters for the notification.
    """
    try:
        if process.stdin is None:
            return
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        data = json.dumps(notification) + "\n"
        process.stdin.write(data.encode("utf-8"))
        process.stdin.flush()
    except Exception as e:
        logger.debug("Failed to send notification '%s': %s", method, e)
