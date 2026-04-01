"""PAGAL OS Computer Use Tool — control mouse, keyboard, and screen.

Provides pyautogui-based tools for agents to interact with the desktop:
screenshot, click, type, hotkey, mouse movement, scroll, and image search.

Safety: FAILSAFE is enabled (move mouse to top-left corner to abort).
All actions are audit-logged and have a small delay to prevent runaway execution.
"""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.tools.registry import register_tool

logger = logging.getLogger("pagal_os")

# Try importing pyautogui — gracefully degrade if not installed
try:
    import pyautogui

    pyautogui.FAILSAFE = True  # Move mouse to (0,0) corner = emergency stop
    _PYAUTOGUI_AVAILABLE = True
except ImportError:
    pyautogui = None  # type: ignore[assignment]
    _PYAUTOGUI_AVAILABLE = False
    logger.warning("pyautogui not installed — computer use tools will be unavailable")

# Directory for saved screenshots
_SCREENSHOTS_DIR = Path.home() / ".pagal-os" / "screenshots"

# Small delay between actions to prevent runaway execution (seconds)
_ACTION_DELAY = 0.1


def _audit(action: str, details: str = "") -> None:
    """Write an audit log entry for a computer-use action.

    Args:
        action: Short action label (e.g. "click", "type_text").
        details: Human-readable detail string.
    """
    try:
        from src.core.security import audit_log

        audit_log(f"computer_{action}", "computer_agent", details)
    except Exception as e:
        logger.debug("Audit log unavailable: %s", e)


def _check_available() -> dict[str, Any] | None:
    """Return an error dict if pyautogui is not available, else None."""
    if not _PYAUTOGUI_AVAILABLE:
        return {"ok": False, "error": "pyautogui is not installed — run: pip install pyautogui"}
    return None


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------


def screenshot() -> dict[str, Any]:
    """Take a screenshot and save it to ~/.pagal-os/screenshots/{timestamp}.png.

    Returns:
        Dict with 'ok', 'path' (saved file path), and 'size' (width, height).
    """
    err = _check_available()
    if err:
        return err

    try:
        _SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        filepath = _SCREENSHOTS_DIR / f"{timestamp}.png"

        img = pyautogui.screenshot()
        img.save(str(filepath))

        _audit("screenshot", f"path={filepath}")
        logger.info("Screenshot saved: %s", filepath)
        time.sleep(_ACTION_DELAY)

        return {
            "ok": True,
            "path": str(filepath),
            "size": {"width": img.width, "height": img.height},
        }
    except Exception as e:
        logger.error("Screenshot failed: %s", e)
        return {"ok": False, "error": f"Screenshot failed: {e}"}


def click(x: int, y: int) -> dict[str, Any]:
    """Click the mouse at the given screen coordinates.

    Args:
        x: Horizontal pixel position.
        y: Vertical pixel position.

    Returns:
        Dict with 'ok' and 'clicked' coordinate pair.
    """
    err = _check_available()
    if err:
        return err

    try:
        pyautogui.click(x, y)
        _audit("click", f"x={x} y={y}")
        logger.info("Clicked at (%d, %d)", x, y)
        time.sleep(_ACTION_DELAY)

        return {"ok": True, "clicked": [x, y]}
    except Exception as e:
        logger.error("Click failed: %s", e)
        return {"ok": False, "error": f"Click failed: {e}"}


def type_text(text: str) -> dict[str, Any]:
    """Type text using the keyboard.

    Args:
        text: The string to type.

    Returns:
        Dict with 'ok' and 'typed' text.
    """
    err = _check_available()
    if err:
        return err

    try:
        pyautogui.typewrite(text, interval=0.02)
        _audit("type_text", f"length={len(text)}")
        logger.info("Typed %d characters", len(text))
        time.sleep(_ACTION_DELAY)

        return {"ok": True, "typed": text}
    except Exception as e:
        logger.error("Type text failed: %s", e)
        return {"ok": False, "error": f"Type text failed: {e}"}


def hotkey(*keys: str) -> dict[str, Any]:
    """Press a keyboard shortcut (e.g. hotkey("ctrl", "c")).

    Args:
        *keys: Key names to press simultaneously.

    Returns:
        Dict with 'ok' and 'keys' pressed.
    """
    err = _check_available()
    if err:
        return err

    try:
        pyautogui.hotkey(*keys)
        key_str = "+".join(keys)
        _audit("hotkey", f"keys={key_str}")
        logger.info("Pressed hotkey: %s", key_str)
        time.sleep(_ACTION_DELAY)

        return {"ok": True, "keys": list(keys)}
    except Exception as e:
        logger.error("Hotkey failed: %s", e)
        return {"ok": False, "error": f"Hotkey failed: {e}"}


def move_mouse(x: int, y: int) -> dict[str, Any]:
    """Move the mouse cursor to the given screen coordinates.

    Args:
        x: Horizontal pixel position.
        y: Vertical pixel position.

    Returns:
        Dict with 'ok' and 'moved_to' coordinate pair.
    """
    err = _check_available()
    if err:
        return err

    try:
        pyautogui.moveTo(x, y)
        _audit("move_mouse", f"x={x} y={y}")
        logger.info("Mouse moved to (%d, %d)", x, y)
        time.sleep(_ACTION_DELAY)

        return {"ok": True, "moved_to": [x, y]}
    except Exception as e:
        logger.error("Move mouse failed: %s", e)
        return {"ok": False, "error": f"Move mouse failed: {e}"}


def scroll(clicks: int) -> dict[str, Any]:
    """Scroll the mouse wheel up (positive) or down (negative).

    Args:
        clicks: Number of scroll increments. Positive = up, negative = down.

    Returns:
        Dict with 'ok', 'clicks', and 'direction'.
    """
    err = _check_available()
    if err:
        return err

    try:
        pyautogui.scroll(clicks)
        direction = "up" if clicks > 0 else "down"
        _audit("scroll", f"clicks={clicks} direction={direction}")
        logger.info("Scrolled %s by %d clicks", direction, abs(clicks))
        time.sleep(_ACTION_DELAY)

        return {"ok": True, "clicks": clicks, "direction": direction}
    except Exception as e:
        logger.error("Scroll failed: %s", e)
        return {"ok": False, "error": f"Scroll failed: {e}"}


def locate_on_screen(image_path: str) -> dict[str, Any]:
    """Find an image on the screen and return its center coordinates.

    Args:
        image_path: Path to the template image file to search for.

    Returns:
        Dict with 'ok', 'found' (bool), and 'x'/'y' if located.
    """
    err = _check_available()
    if err:
        return err

    try:
        location = pyautogui.locateOnScreen(image_path)
        if location is not None:
            center = pyautogui.center(location)
            _audit("locate_on_screen", f"found=True image={image_path} x={center.x} y={center.y}")
            logger.info("Image found at (%d, %d): %s", center.x, center.y, image_path)
            return {
                "ok": True,
                "found": True,
                "x": center.x,
                "y": center.y,
                "region": {
                    "left": location.left,
                    "top": location.top,
                    "width": location.width,
                    "height": location.height,
                },
            }
        else:
            _audit("locate_on_screen", f"found=False image={image_path}")
            logger.info("Image not found on screen: %s", image_path)
            return {"ok": True, "found": False}
    except Exception as e:
        logger.error("Locate on screen failed: %s", e)
        return {"ok": False, "error": f"Locate on screen failed: {e}"}


def get_screen_size() -> dict[str, Any]:
    """Get the screen dimensions in pixels.

    Returns:
        Dict with 'ok', 'width', and 'height'.
    """
    err = _check_available()
    if err:
        return err

    try:
        size = pyautogui.size()
        _audit("get_screen_size", f"width={size.width} height={size.height}")
        logger.info("Screen size: %dx%d", size.width, size.height)

        return {"ok": True, "width": size.width, "height": size.height}
    except Exception as e:
        logger.error("Get screen size failed: %s", e)
        return {"ok": False, "error": f"Get screen size failed: {e}"}


# ---------------------------------------------------------------------------
# Register all tools in the registry
# ---------------------------------------------------------------------------

register_tool(
    name="screenshot",
    function=screenshot,
    description="Take a screenshot and save it to disk. Returns the file path.",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)

register_tool(
    name="click",
    function=click,
    description="Click the mouse at the given screen coordinates.",
    parameters={
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "Horizontal pixel position"},
            "y": {"type": "integer", "description": "Vertical pixel position"},
        },
        "required": ["x", "y"],
    },
)

register_tool(
    name="type_text",
    function=type_text,
    description="Type text using the keyboard.",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to type"},
        },
        "required": ["text"],
    },
)

register_tool(
    name="hotkey",
    function=hotkey,
    description="Press a keyboard shortcut (e.g. ctrl+c). Pass each key as a separate argument.",
    parameters={
        "type": "object",
        "properties": {
            "keys": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Key names to press simultaneously (e.g. ['ctrl', 'c'])",
            },
        },
        "required": ["keys"],
    },
)

register_tool(
    name="move_mouse",
    function=move_mouse,
    description="Move the mouse cursor to the given screen coordinates.",
    parameters={
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "Horizontal pixel position"},
            "y": {"type": "integer", "description": "Vertical pixel position"},
        },
        "required": ["x", "y"],
    },
)

register_tool(
    name="scroll",
    function=scroll,
    description="Scroll the mouse wheel. Positive = up, negative = down.",
    parameters={
        "type": "object",
        "properties": {
            "clicks": {
                "type": "integer",
                "description": "Scroll increments (positive=up, negative=down)",
            },
        },
        "required": ["clicks"],
    },
)

register_tool(
    name="locate_on_screen",
    function=locate_on_screen,
    description="Find an image on the screen and return its coordinates.",
    parameters={
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Path to the template image to search for on screen",
            },
        },
        "required": ["image_path"],
    },
)

register_tool(
    name="get_screen_size",
    function=get_screen_size,
    description="Get the screen dimensions (width and height in pixels).",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
