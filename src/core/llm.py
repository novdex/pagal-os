"""PAGAL OS LLM provider — unified interface for OpenRouter and Ollama."""

import logging
import os
from typing import Any

import httpx
from dotenv import load_dotenv

logger = logging.getLogger("pagal_os")

# Ensure .env is loaded
load_dotenv()


def call_llm(
    messages: list[dict[str, str]],
    model: str,
    tools: list[dict] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """Call an LLM via OpenRouter or Ollama.

    Routes to Ollama if model starts with 'ollama/', otherwise uses OpenRouter.

    Args:
        messages: List of message dicts with 'role' and 'content' keys.
        model: Model identifier (e.g. 'ollama/llama3' or 'nvidia/nemotron-...').
        tools: Optional list of tool schemas in OpenAI function-calling format.
        timeout: Request timeout in seconds.

    Returns:
        Dict with keys: ok (bool), content (str), tool_calls (list|None), error (str).
    """
    if model.startswith("ollama/"):
        return _call_ollama(messages, model, tools, timeout)
    else:
        return _call_openrouter(messages, model, tools, timeout)


def _call_ollama(
    messages: list[dict],
    model: str,
    tools: list[dict] | None,
    timeout: int,
) -> dict[str, Any]:
    """Call Ollama local API.

    Args:
        messages: Chat messages.
        model: Model name prefixed with 'ollama/'.
        tools: Optional tool schemas.
        timeout: Request timeout in seconds.

    Returns:
        Standardized response dict.
    """
    from src.core.config import get_config

    config = get_config()
    model_name = model.removeprefix("ollama/")
    url = f"{config.ollama_url}/api/chat"

    payload: dict[str, Any] = {
        "model": model_name,
        "messages": messages,
        "stream": False,
    }
    if tools:
        payload["tools"] = tools

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        message = data.get("message", {})
        content = message.get("content", "")
        tool_calls = message.get("tool_calls")

        return {
            "ok": True,
            "content": content,
            "tool_calls": tool_calls,
            "error": "",
        }

    except httpx.TimeoutException:
        logger.error("Ollama request timed out after %ds", timeout)
        return {"ok": False, "content": "", "tool_calls": None, "error": f"Timeout after {timeout}s"}
    except httpx.HTTPStatusError as e:
        logger.error("Ollama HTTP error: %s", e)
        return {"ok": False, "content": "", "tool_calls": None, "error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        logger.error("Ollama request failed: %s", e)
        return {"ok": False, "content": "", "tool_calls": None, "error": str(e)}


def _call_openrouter(
    messages: list[dict],
    model: str,
    tools: list[dict] | None,
    timeout: int,
) -> dict[str, Any]:
    """Call OpenRouter API.

    Args:
        messages: Chat messages.
        model: Model identifier for OpenRouter.
        tools: Optional tool schemas.
        timeout: Request timeout in seconds.

    Returns:
        Standardized response dict.
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        return {"ok": False, "content": "", "tool_calls": None, "error": "OPENROUTER_API_KEY not set"}

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://pagal-os.local",
        "X-Title": "PAGAL OS",
    }

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if tools:
        payload["tools"] = tools

    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices", [])
        if not choices:
            return {"ok": False, "content": "", "tool_calls": None, "error": "No choices in response"}

        message = choices[0].get("message", {})
        content = message.get("content", "")
        tool_calls_raw = message.get("tool_calls")

        # Normalize tool_calls to consistent format
        tool_calls = None
        if tool_calls_raw:
            tool_calls = []
            for tc in tool_calls_raw:
                tool_calls.append({
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc.get("function", {}).get("name", ""),
                        "arguments": tc.get("function", {}).get("arguments", "{}"),
                    },
                })

        return {
            "ok": True,
            "content": content or "",
            "tool_calls": tool_calls,
            "error": "",
        }

    except httpx.TimeoutException:
        logger.error("OpenRouter request timed out after %ds", timeout)
        return {"ok": False, "content": "", "tool_calls": None, "error": f"Timeout after {timeout}s"}
    except httpx.HTTPStatusError as e:
        logger.error("OpenRouter HTTP error: %s", e)
        return {"ok": False, "content": "", "tool_calls": None, "error": f"HTTP {e.response.status_code}: {e.response.text}"}
    except Exception as e:
        logger.error("OpenRouter request failed: %s", e)
        return {"ok": False, "content": "", "tool_calls": None, "error": str(e)}
