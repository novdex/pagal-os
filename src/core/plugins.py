"""Plugin System — drop-in Python files that extend PAGAL OS.

Drop a .py file into ~/.pagal-os/plugins/ and it will be auto-loaded on startup.
Each plugin can register tools, add API routes, or extend agent capabilities.

Plugin structure:
    ~/.pagal-os/plugins/
        weather.py          # Registers a get_weather tool
        my_custom_tool.py   # Registers custom tools
        README.md           # Ignored (not .py)

Plugin file example:
    from src.tools.registry import register_tool

    def get_weather(city: str) -> dict:
        import httpx
        resp = httpx.get(f"https://wttr.in/{city}?format=j1")
        return {"ok": True, "result": resp.json()["current_condition"][0]}

    register_tool(
        name="get_weather",
        function=get_weather,
        description="Get current weather for a city",
        parameters={
            "type": "object",
            "properties": {"city": {"type": "string", "description": "City name"}},
            "required": ["city"],
        },
    )
"""

import importlib
import importlib.util
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("pagal_os")

_PLUGINS_DIR = Path.home() / ".pagal-os" / "plugins"
_loaded_plugins: dict[str, Any] = {}


def get_plugins_dir() -> Path:
    """Get the plugins directory, creating it if needed."""
    _PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    return _PLUGINS_DIR


def load_plugins() -> dict[str, Any]:
    """Load all .py plugins from the plugins directory.

    Returns:
        Dict mapping plugin name -> {"file": path, "status": "loaded"|"error", "error": str}.
    """
    plugins_dir = get_plugins_dir()
    results: dict[str, Any] = {}

    for py_file in sorted(plugins_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue

        name = py_file.stem
        try:
            spec = importlib.util.spec_from_file_location(
                f"pagal_plugin_{name}", py_file
            )
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                _loaded_plugins[name] = module
                results[name] = {"file": str(py_file), "status": "loaded"}
                logger.info("Loaded plugin: %s", name)
        except Exception as e:
            results[name] = {"file": str(py_file), "status": "error", "error": str(e)}
            logger.warning("Failed to load plugin '%s': %s", name, e)

    return results


def list_plugins() -> list[dict[str, Any]]:
    """List all plugins (loaded and available on disk).

    Returns:
        List of plugin info dicts.
    """
    plugins_dir = get_plugins_dir()
    result: list[dict[str, Any]] = []

    for py_file in sorted(plugins_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        name = py_file.stem
        result.append({
            "name": name,
            "file": str(py_file),
            "loaded": name in _loaded_plugins,
            "size_bytes": py_file.stat().st_size,
        })

    return result


def create_plugin_template(name: str) -> dict[str, Any]:
    """Create a starter plugin file from a template.

    Args:
        name: Plugin name (will create {name}.py).

    Returns:
        Dict with 'ok' and file path.
    """
    plugins_dir = get_plugins_dir()
    plugin_path = plugins_dir / f"{name}.py"

    if plugin_path.exists():
        return {"ok": False, "error": f"Plugin '{name}' already exists at {plugin_path}"}

    template = f'''"""PAGAL OS Plugin: {name}

Drop this file in ~/.pagal-os/plugins/ and restart the server.
It will be auto-loaded and the tools will be available to all agents.
"""

from typing import Any
from src.tools.registry import register_tool


def {name}_action(input_text: str) -> dict[str, Any]:
    """Your custom tool function.

    Args:
        input_text: The input from the agent.

    Returns:
        Dict with 'ok' and 'result' keys.
    """
    # TODO: Implement your logic here
    return {{"ok": True, "result": f"Plugin {name} processed: {{input_text}}"}}


# Register the tool so agents can use it
register_tool(
    name="{name}",
    function={name}_action,
    description="Custom plugin: {name}",
    parameters={{
        "type": "object",
        "properties": {{
            "input_text": {{"type": "string", "description": "Input for the plugin"}},
        }},
        "required": ["input_text"],
    }},
)
'''

    try:
        plugin_path.write_text(template, encoding="utf-8")
        return {"ok": True, "path": str(plugin_path), "message": f"Plugin template created at {plugin_path}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
