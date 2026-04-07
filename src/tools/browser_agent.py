"""Browser Agent — AI-driven web automation using Playwright.

Agents can navigate websites, click buttons, fill forms, take screenshots,
and extract data — like a human using a browser.

Requires: playwright package (pip install playwright && playwright install chromium)
Falls back gracefully if not installed.
"""

import base64
import logging
import tempfile
from pathlib import Path
from typing import Any

from src.tools.registry import register_tool

logger = logging.getLogger("pagal_os")


def _check_playwright() -> str | None:
    """Check if playwright is available. Returns error message or None."""
    try:
        import playwright  # noqa: F401
        return None
    except ImportError:
        return "playwright not installed. Run: pip install playwright && playwright install chromium"


def browse_and_interact(
    url: str,
    actions: list[dict[str, Any]] | None = None,
    screenshot: bool = False,
    extract_text: bool = True,
    wait_seconds: int = 3,
) -> dict[str, Any]:
    """Navigate to a URL and optionally perform actions (click, type, etc.).

    Args:
        url: URL to navigate to.
        actions: List of actions to perform. Each action is a dict:
            {"type": "click", "selector": "button.submit"}
            {"type": "fill", "selector": "input[name=email]", "value": "user@example.com"}
            {"type": "wait", "seconds": 2}
            {"type": "scroll", "direction": "down"}
        screenshot: Whether to take a screenshot after actions.
        extract_text: Whether to extract page text.
        wait_seconds: Seconds to wait for page load.

    Returns:
        Dict with 'ok', 'text', 'screenshot_path', 'title', 'url'.
    """
    err = _check_playwright()
    if err:
        return {"ok": False, "error": err}

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # Navigate
            page.goto(url, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=wait_seconds * 1000)

            # Execute actions
            if actions:
                for action in actions:
                    act_type = action.get("type", "")
                    selector = action.get("selector", "")

                    if act_type == "click" and selector:
                        page.click(selector, timeout=5000)
                    elif act_type == "fill" and selector:
                        page.fill(selector, action.get("value", ""), timeout=5000)
                    elif act_type == "wait":
                        page.wait_for_timeout(action.get("seconds", 1) * 1000)
                    elif act_type == "scroll":
                        direction = action.get("direction", "down")
                        page.evaluate(f"window.scrollBy(0, {'500' if direction == 'down' else '-500'})")
                    elif act_type == "press" and selector:
                        page.press(selector, action.get("key", "Enter"))

                # Wait after actions
                page.wait_for_timeout(1000)

            result: dict[str, Any] = {
                "ok": True,
                "title": page.title(),
                "url": page.url,
            }

            # Extract text
            if extract_text:
                text = page.inner_text("body")
                result["text"] = text[:10000] if text else ""

            # Screenshot
            if screenshot:
                ss_path = Path(tempfile.mkdtemp()) / "screenshot.png"
                page.screenshot(path=str(ss_path), full_page=False)
                result["screenshot_path"] = str(ss_path)

            browser.close()
            return result

    except Exception as e:
        logger.error("Browser agent failed: %s", e)
        return {"ok": False, "error": str(e)}


def fill_form(
    url: str,
    fields: dict[str, str],
    submit_selector: str = "button[type=submit]",
) -> dict[str, Any]:
    """Navigate to a URL, fill form fields, and submit.

    Args:
        url: URL of the page with the form.
        fields: Dict of CSS selector -> value to fill.
        submit_selector: CSS selector for the submit button.

    Returns:
        Dict with 'ok' and page text after submission.
    """
    actions = []
    for selector, value in fields.items():
        actions.append({"type": "fill", "selector": selector, "value": value})
    actions.append({"type": "click", "selector": submit_selector})
    actions.append({"type": "wait", "seconds": 3})

    return browse_and_interact(url, actions=actions, extract_text=True)


# Auto-register tools
register_tool(
    name="browse_and_interact",
    function=browse_and_interact,
    description="Navigate to a URL and interact with the page — click buttons, fill forms, take screenshots. Like a human using a browser.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to navigate to"},
            "actions": {
                "type": "array",
                "description": "List of actions: {type: 'click'|'fill'|'wait'|'scroll', selector: 'css', value: 'text'}",
                "items": {"type": "object"},
            },
            "screenshot": {"type": "boolean", "description": "Take a screenshot", "default": False},
            "extract_text": {"type": "boolean", "description": "Extract page text", "default": True},
        },
        "required": ["url"],
    },
)

register_tool(
    name="fill_form",
    function=fill_form,
    description="Fill out a web form and submit it. Provide the URL, a dict of CSS selectors to values, and optionally a submit button selector.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL of the form page"},
            "fields": {"type": "object", "description": "CSS selector -> value mapping for form fields"},
            "submit_selector": {"type": "string", "description": "CSS selector for submit button", "default": "button[type=submit]"},
        },
        "required": ["url", "fields"],
    },
)
