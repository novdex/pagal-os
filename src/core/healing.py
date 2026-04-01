"""PAGAL OS Self-Healing Workflows — retry, fallback, and graceful degradation.

When tools or LLM calls fail, this module automatically retries with exponential
backoff, tries alternative tools, or gracefully degrades instead of crashing.
"""

import logging
import time
from typing import Any, Callable

logger = logging.getLogger("pagal_os")

# Map of tools to their alternatives when the primary tool fails
TOOL_ALTERNATIVES: dict[str, list[str]] = {
    "search_web": ["browse_url"],
    "browse_url": ["search_web"],
    "run_shell": [],
    "read_file": [],
    "write_file": [],
    "analyze_image": [],
    "read_pdf": [],
    "transcribe_audio": [],
}


def with_retry(
    func: Callable[..., Any],
    max_retries: int = 3,
    delay: float = 2.0,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Retry a function N times with exponential backoff.

    Args:
        func: The callable to retry.
        max_retries: Maximum number of retry attempts.
        delay: Initial delay in seconds between retries (doubles each time).
        *args: Positional arguments to pass to func.
        **kwargs: Keyword arguments to pass to func.

    Returns:
        The result of the function call.

    Raises:
        Exception: The last exception if all retries fail.
    """
    last_error: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_error = e
            if attempt < max_retries:
                wait_time = delay * (2 ** attempt)
                logger.warning(
                    "Retry %d/%d for %s failed: %s — waiting %.1fs",
                    attempt + 1, max_retries, func.__name__, e, wait_time,
                )
                time.sleep(wait_time)
            else:
                logger.error(
                    "All %d retries exhausted for %s: %s",
                    max_retries, func.__name__, e,
                )

    if last_error:
        raise last_error
    raise RuntimeError(f"Unexpected state in with_retry for {func.__name__}")


def with_fallback(
    primary_func: Callable[..., Any],
    fallback_func: Callable[..., Any],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Try primary function, if it fails try the fallback.

    Args:
        primary_func: The preferred callable to try first.
        fallback_func: The backup callable if primary fails.
        *args: Positional arguments passed to both functions.
        **kwargs: Keyword arguments passed to both functions.

    Returns:
        The result from whichever function succeeds.

    Raises:
        Exception: If both primary and fallback fail, raises the fallback's error.
    """
    try:
        return primary_func(*args, **kwargs)
    except Exception as primary_error:
        logger.warning(
            "Primary function %s failed: %s — trying fallback %s",
            primary_func.__name__, primary_error, fallback_func.__name__,
        )
        try:
            return fallback_func(*args, **kwargs)
        except Exception as fallback_error:
            logger.error(
                "Fallback %s also failed: %s",
                fallback_func.__name__, fallback_error,
            )
            raise fallback_error from primary_error


def heal_tool_failure(
    tool_name: str,
    args: dict[str, Any],
    error: str,
    execute_tool_fn: Callable | None = None,
) -> dict[str, Any]:
    """Attempt to recover from a tool failure through multiple strategies.

    Strategy order:
    1. Retry the same tool (transient failure)
    2. Try alternative tool (if one exists in TOOL_ALTERNATIVES)
    3. Return partial result with error message (never crash)

    Args:
        tool_name: The name of the tool that failed.
        args: The arguments that were passed to the tool.
        error: The error message from the failure.
        execute_tool_fn: The function used to execute tools (from registry).

    Returns:
        Dict with 'ok', 'result' or 'error' keys. Always returns, never raises.
    """
    if execute_tool_fn is None:
        try:
            from src.tools.registry import execute_tool
            execute_tool_fn = execute_tool
        except ImportError:
            return {
                "ok": False,
                "error": f"Tool '{tool_name}' failed: {error} (no execute_tool available)",
                "healed": False,
            }

    # Strategy 1: Retry the same tool once
    logger.info("Healing: retrying tool '%s'...", tool_name)
    try:
        retry_result = execute_tool_fn(tool_name, args)
        if isinstance(retry_result, dict) and retry_result.get("ok"):
            logger.info("Healing: retry of '%s' succeeded", tool_name)
            return {**retry_result, "healed": True, "strategy": "retry"}
    except Exception as retry_err:
        logger.debug("Healing: retry of '%s' also failed: %s", tool_name, retry_err)

    # Strategy 2: Try alternative tools
    alternatives = TOOL_ALTERNATIVES.get(tool_name, [])
    for alt_tool in alternatives:
        logger.info("Healing: trying alternative tool '%s' instead of '%s'", alt_tool, tool_name)
        try:
            # Map arguments as best we can
            alt_args = _map_args_for_alternative(tool_name, alt_tool, args)
            alt_result = execute_tool_fn(alt_tool, alt_args)
            if isinstance(alt_result, dict) and alt_result.get("ok"):
                logger.info("Healing: alternative '%s' succeeded", alt_tool)
                return {**alt_result, "healed": True, "strategy": f"alternative:{alt_tool}"}
        except Exception as alt_err:
            logger.debug("Healing: alternative '%s' failed: %s", alt_tool, alt_err)

    # Strategy 3: Return partial result with error (graceful degradation)
    logger.warning(
        "Healing: all strategies failed for tool '%s'. Degrading gracefully.",
        tool_name,
    )
    return {
        "ok": False,
        "error": (
            f"Tool '{tool_name}' failed: {error}. "
            f"Tried retry and {len(alternatives)} alternative(s). "
            "No recovery possible."
        ),
        "healed": False,
        "strategy": "degraded",
    }


def heal_llm_failure(
    model: str,
    messages: list[dict[str, str]],
    error: str,
    call_llm_fn: Callable | None = None,
    tools: list[dict] | None = None,
) -> dict[str, Any]:
    """Attempt to recover from an LLM call failure.

    Strategy order:
    1. Retry the same model (transient failure)
    2. Try fallback model (cloud fails -> try local Ollama)
    3. Return error message (never crash)

    Args:
        model: The model that failed.
        messages: The messages that were sent.
        error: The error message from the failure.
        call_llm_fn: The function used to call LLMs.
        tools: Optional tool schemas.

    Returns:
        Dict with standard LLM response keys. Always returns, never raises.
    """
    if call_llm_fn is None:
        try:
            from src.core.llm import call_llm
            call_llm_fn = call_llm
        except ImportError:
            return {
                "ok": False,
                "content": "",
                "tool_calls": None,
                "error": f"LLM '{model}' failed: {error} (no call_llm available)",
            }

    # Strategy 1: Retry the same model
    logger.info("Healing: retrying LLM model '%s'...", model)
    try:
        retry_result = call_llm_fn(messages=messages, model=model, tools=tools, timeout=90)
        if retry_result.get("ok"):
            logger.info("Healing: retry of model '%s' succeeded", model)
            return retry_result
    except Exception as retry_err:
        logger.debug("Healing: retry of '%s' also failed: %s", model, retry_err)

    # Strategy 2: Try fallback model
    fallback_models = _get_fallback_models(model)
    for fallback in fallback_models:
        logger.info("Healing: trying fallback model '%s' instead of '%s'", fallback, model)
        try:
            fallback_result = call_llm_fn(
                messages=messages, model=fallback, tools=tools, timeout=90,
            )
            if fallback_result.get("ok"):
                logger.info("Healing: fallback model '%s' succeeded", fallback)
                return fallback_result
        except Exception as fb_err:
            logger.debug("Healing: fallback '%s' failed: %s", fallback, fb_err)

    # Strategy 3: Return error message (never crash)
    logger.warning(
        "Healing: all LLM strategies failed for model '%s'. Returning error.",
        model,
    )
    return {
        "ok": False,
        "content": "",
        "tool_calls": None,
        "error": (
            f"LLM '{model}' failed: {error}. "
            f"Tried retry and {len(fallback_models)} fallback model(s). "
            "No recovery possible."
        ),
    }


def _get_fallback_models(model: str) -> list[str]:
    """Determine fallback models based on the current model.

    If the model is a cloud model, try local Ollama. If it's Ollama, try a
    different Ollama model.

    Args:
        model: The model that failed.

    Returns:
        List of fallback model identifiers to try.
    """
    if model.startswith("ollama/"):
        # Already local — try a different local model
        local_fallbacks = ["ollama/llama3", "ollama/mistral", "ollama/phi3"]
        return [m for m in local_fallbacks if m != model]
    else:
        # Cloud model failed — try local Ollama as fallback
        return ["ollama/llama3"]


def _map_args_for_alternative(
    original_tool: str,
    alt_tool: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Map arguments from one tool to an alternative tool's expected format.

    Args:
        original_tool: The tool that failed.
        alt_tool: The alternative tool to try.
        args: The original arguments.

    Returns:
        Mapped arguments suitable for the alternative tool.
    """
    # search_web -> browse_url: use query as a DuckDuckGo search URL
    if original_tool == "search_web" and alt_tool == "browse_url":
        query = args.get("query", "")
        return {"url": f"https://duckduckgo.com/html/?q={query}"}

    # browse_url -> search_web: extract domain/path as search query
    if original_tool == "browse_url" and alt_tool == "search_web":
        url = args.get("url", "")
        return {"query": url, "num_results": 3}

    # Default: pass through unchanged
    return args
