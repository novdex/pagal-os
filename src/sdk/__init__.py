"""PAGAL OS Agent SDK — build agents in Python code instead of YAML.

Usage::

    from pagal_os.sdk import Agent, tool

    class MyAgent(Agent):
        name = "my_custom_agent"
        description = "Does custom things"

        @tool("Search the web")
        def search(self, query: str) -> str:
            return self.think(f"Search for: {query}")

        def run(self, task: str) -> str:
            return self.think(task)
"""

from src.sdk.agent import Agent, load_sdk_agents  # noqa: F401
from src.sdk.decorators import tool  # noqa: F401

__all__ = ["Agent", "tool", "load_sdk_agents"]
