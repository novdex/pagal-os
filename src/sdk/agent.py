"""SDK Agent base class — lets developers build agents in Python code.

Provides ``think()``, ``use_tool()``, ``remember()``, and ``recall()`` so
that a Python class can do everything a YAML agent can, and more.
"""

import importlib.util
import inspect
import logging
from pathlib import Path
from typing import Any

from src.core.config import get_config
from src.core.llm import call_llm
from src.tools.registry import execute_tool

logger = logging.getLogger("pagal_os")

# Where user-authored SDK agents live
SDK_AGENTS_DIR = Path.home() / ".pagal-os" / "sdk_agents"


class Agent:
    """Base class for code-defined PAGAL OS agents.

    Subclass this and override ``run()`` to create a custom agent.

    Class attributes:
        name: Unique snake_case identifier.
        description: What the agent does.
        model: LLM model string (defaults to config default).
    """

    name: str = "unnamed_agent"
    description: str = ""
    model: str = ""

    def __init__(self) -> None:
        """Initialise the agent and discover decorated tools."""
        config = get_config()
        if not self.model:
            self.model = config.default_model

        # Discover @tool-decorated methods
        self._tools: dict[str, dict[str, Any]] = {}
        for attr_name in dir(self):
            try:
                attr = getattr(self, attr_name)
                if callable(attr) and hasattr(attr, "_tool_meta"):
                    meta = attr._tool_meta
                    self._tools[meta["name"]] = {
                        "description": meta["description"],
                        "callable": attr,
                    }
            except Exception:
                continue

    def think(self, prompt: str) -> str:
        """Send a prompt to the LLM and return the text response.

        Args:
            prompt: The question or instruction.

        Returns:
            The LLM's text response, or an error string.
        """
        try:
            result = call_llm(
                messages=[
                    {"role": "system", "content": self.description or "You are a helpful assistant."},
                    {"role": "user", "content": prompt},
                ],
                model=self.model,
                timeout=60,
            )
            if result["ok"]:
                return result["content"]
            return f"[LLM error] {result['error']}"
        except Exception as e:
            logger.error("Agent '%s' think() failed: %s", self.name, e)
            return f"[error] {e}"

    def use_tool(self, tool_name: str, **kwargs: Any) -> dict[str, Any]:
        """Call a registered PAGAL OS tool or a local @tool method.

        Args:
            tool_name: Name of the tool to invoke.
            **kwargs: Arguments for the tool.

        Returns:
            Tool result dict.
        """
        try:
            # Check local SDK tools first
            if tool_name in self._tools:
                result = self._tools[tool_name]["callable"](**kwargs)
                return {"ok": True, "result": result}

            # Fall back to global tool registry
            return execute_tool(tool_name, kwargs)
        except Exception as e:
            logger.error("Agent '%s' use_tool(%s) failed: %s", self.name, tool_name, e)
            return {"ok": False, "error": str(e)}

    def remember(self, topic: str, content: str) -> int:
        """Save a fact to the knowledge graph.

        Args:
            topic: Short topic label.
            content: The fact or information.

        Returns:
            The knowledge node ID, or -1 on failure.
        """
        try:
            from src.core.knowledge import add_knowledge
            return add_knowledge(self.name, topic, content, source="sdk")
        except Exception as e:
            logger.error("Agent '%s' remember() failed: %s", self.name, e)
            return -1

    def recall(self, query: str) -> list[dict[str, Any]]:
        """Search the knowledge graph for relevant facts.

        Args:
            query: Search string.

        Returns:
            List of matching knowledge node dicts.
        """
        try:
            from src.core.knowledge import search_knowledge
            return search_knowledge(query, agent_name=self.name)
        except Exception as e:
            logger.error("Agent '%s' recall() failed: %s", self.name, e)
            return []

    def run(self, task: str) -> str:
        """Execute the agent's main logic. Override in subclasses.

        Args:
            task: The user's task description.

        Returns:
            The result text.
        """
        return self.think(task)


def load_sdk_agents(sdk_dir: Path | None = None) -> list[Agent]:
    """Scan a directory for Python files that define Agent subclasses.

    Imports each .py file and collects all ``Agent`` subclass instances.

    Args:
        sdk_dir: Directory to scan. Defaults to ~/.pagal-os/sdk_agents/.

    Returns:
        List of instantiated Agent subclass objects.
    """
    sdk_dir = sdk_dir or SDK_AGENTS_DIR
    agents: list[Agent] = []

    if not sdk_dir.exists():
        try:
            sdk_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error("Failed to create SDK agents dir: %s", e)
            return agents

    try:
        for py_file in sorted(sdk_dir.glob("*.py")):
            try:
                spec = importlib.util.spec_from_file_location(
                    py_file.stem, str(py_file),
                )
                if spec is None or spec.loader is None:
                    continue

                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)  # type: ignore[union-attr]

                # Find all Agent subclasses in the module
                for _name, obj in inspect.getmembers(module, inspect.isclass):
                    if issubclass(obj, Agent) and obj is not Agent:
                        agent_instance = obj()
                        agents.append(agent_instance)
                        logger.info(
                            "Loaded SDK agent '%s' from %s",
                            agent_instance.name,
                            py_file,
                        )
            except Exception as e:
                logger.warning("Failed to load SDK agent from %s: %s", py_file, e)
    except Exception as e:
        logger.error("Failed to scan SDK agents dir: %s", e)

    return agents
