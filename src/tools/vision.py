"""Multimodal Vision — agents that see and understand images.

Supports sending images to vision-capable LLMs for:
  - Image description and analysis
  - OCR (text extraction from images)
  - Screenshot understanding
  - Document/receipt reading
  - Visual QA ("What's in this image?")

Works with: GPT-4o, Claude (vision), Qwen-VL, or any OpenAI-compatible vision API.
"""

import base64
import logging
import os
from pathlib import Path
from typing import Any

import httpx

from src.tools.registry import register_tool

logger = logging.getLogger("pagal_os")


def _image_to_base64(image_path: str) -> str | None:
    """Read an image file and encode as base64 data URI."""
    try:
        path = Path(image_path).expanduser().resolve()
        if not path.exists():
            return None

        # Check path boundaries
        from src.tools.files import _is_path_allowed
        if _is_path_allowed(path):
            return None

        suffix = path.suffix.lower()
        mime_types = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                      ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}
        mime = mime_types.get(suffix, "image/png")

        data = path.read_bytes()
        if len(data) > 20 * 1024 * 1024:  # 20MB limit
            return None

        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{b64}"

    except Exception as e:
        logger.error("Failed to read image: %s", e)
        return None


def analyze_image_with_llm(
    image_path: str = "",
    image_url: str = "",
    question: str = "Describe this image in detail.",
    model: str = "",
) -> dict[str, Any]:
    """Analyze an image using a vision-capable LLM.

    Args:
        image_path: Local file path to an image.
        image_url: URL of an image (alternative to file path).
        question: What to ask about the image.
        model: Vision model to use (default: uses OpenRouter with a vision model).

    Returns:
        Dict with 'ok' and 'result' (the LLM's analysis).
    """
    if not image_path and not image_url:
        return {"ok": False, "error": "Provide either image_path or image_url"}

    try:
        # Build the image content
        image_content: dict[str, Any]
        if image_url:
            image_content = {"type": "image_url", "image_url": {"url": image_url}}
        elif image_path:
            data_uri = _image_to_base64(image_path)
            if not data_uri:
                # If path boundary check fails or file doesn't exist,
                # _is_path_allowed returns None for allowed paths (the function
                # returns error string or None). Let's try reading directly.
                path = Path(image_path).expanduser().resolve()
                if not path.exists():
                    return {"ok": False, "error": f"Image not found: {image_path}"}
                suffix = path.suffix.lower()
                mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                        "gif": "image/gif", "webp": "image/webp"}.get(suffix.lstrip("."), "image/png")
                b64 = base64.b64encode(path.read_bytes()).decode("ascii")
                data_uri = f"data:{mime};base64,{b64}"
            image_content = {"type": "image_url", "image_url": {"url": data_uri}}
        else:
            return {"ok": False, "error": "No image provided"}

        # Use a vision-capable model
        if not model:
            model = os.getenv("VISION_MODEL", "google/gemini-2.0-flash-001")

        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            return {"ok": False, "error": "OPENROUTER_API_KEY not set (needed for vision model)"}

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    image_content,
                ],
            }
        ]

        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": model, "messages": messages, "max_tokens": 1000}

        with httpx.Client(timeout=60) as client:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        return {"ok": True, "result": content, "model": model}

    except Exception as e:
        logger.error("Vision analysis failed: %s", e)
        return {"ok": False, "error": str(e)}


def extract_text_from_image(image_path: str = "", image_url: str = "") -> dict[str, Any]:
    """Extract text (OCR) from an image using a vision model.

    Args:
        image_path: Local path to image.
        image_url: URL of image.

    Returns:
        Dict with 'ok' and 'text' (extracted text).
    """
    result = analyze_image_with_llm(
        image_path=image_path,
        image_url=image_url,
        question="Extract ALL text visible in this image. Return the text exactly as it appears, preserving layout where possible. If there's no text, say 'No text found'.",
    )
    if result["ok"]:
        return {"ok": True, "text": result["result"]}
    return result


# Auto-register tools
register_tool(
    name="analyze_image",
    function=analyze_image_with_llm,
    description="Analyze an image using AI vision — describe it, answer questions about it, or understand its content. Provide a file path or URL.",
    parameters={
        "type": "object",
        "properties": {
            "image_path": {"type": "string", "description": "Local path to the image file", "default": ""},
            "image_url": {"type": "string", "description": "URL of the image", "default": ""},
            "question": {"type": "string", "description": "What to ask about the image", "default": "Describe this image in detail."},
        },
        "required": [],
    },
)

register_tool(
    name="extract_text_ocr",
    function=extract_text_from_image,
    description="Extract text (OCR) from an image — reads receipts, documents, screenshots, signs, etc.",
    parameters={
        "type": "object",
        "properties": {
            "image_path": {"type": "string", "description": "Local path to the image", "default": ""},
            "image_url": {"type": "string", "description": "URL of the image", "default": ""},
        },
        "required": [],
    },
)
