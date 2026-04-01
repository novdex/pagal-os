"""PAGAL OS Multi-Modal Input — agents understand images, PDFs, and audio.

Provides tools for:
- Image analysis via vision-capable models on OpenRouter
- PDF text extraction via pypdf
- Audio transcription via Groq Whisper API

Each function is registered as a tool so any agent can use them.
"""

import base64
import logging
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from src.tools.registry import register_tool

logger = logging.getLogger("pagal_os")

load_dotenv()


def analyze_image(image_path: str, question: str = "") -> dict[str, Any]:
    """Analyse an image by sending it to a vision-capable model on OpenRouter.

    Base64-encodes the image and sends it alongside an optional question.
    Uses a vision model (defaults to openai/gpt-4.1-nano) for analysis.

    Args:
        image_path: Path to the image file (jpg, png, gif, webp).
        question: Optional question about the image. Defaults to 'Describe this image.'

    Returns:
        Dict with 'ok', 'description' (str), and 'model' keys.
    """
    try:
        path = Path(image_path)
        if not path.exists():
            return {"ok": False, "error": f"Image not found: {image_path}"}

        # Detect MIME type from extension
        ext = path.suffix.lower()
        mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        mime_type = mime_map.get(ext, "image/png")

        # Read and base64 encode
        image_data = path.read_bytes()
        b64_image = base64.b64encode(image_data).decode("utf-8")
        data_url = f"data:{mime_type};base64,{b64_image}"

        # Check file size (limit to ~10MB)
        if len(image_data) > 10 * 1024 * 1024:
            return {"ok": False, "error": "Image too large (max 10MB)"}

        # Build message with image
        prompt = question if question else "Describe this image in detail."
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url},
                    },
                ],
            }
        ]

        # Call OpenRouter with a vision model
        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            return {"ok": False, "error": "OPENROUTER_API_KEY not set"}

        model = "openai/gpt-4.1-nano"

        with httpx.Client(timeout=60) as client:
            response = client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json={"model": model, "messages": messages},
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://pagal-os.local",
                    "X-Title": "PAGAL OS",
                },
            )
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices", [])
        if not choices:
            return {"ok": False, "error": "No response from vision model"}

        description = choices[0].get("message", {}).get("content", "")

        logger.info("Analysed image '%s': %d chars", image_path, len(description))
        return {
            "ok": True,
            "description": description,
            "model": model,
        }

    except httpx.HTTPStatusError as e:
        logger.error("Vision API error: %s", e)
        return {"ok": False, "error": f"Vision API HTTP {e.response.status_code}"}
    except Exception as e:
        logger.error("Image analysis failed for '%s': %s", image_path, e)
        return {"ok": False, "error": f"Image analysis failed: {e}"}


def read_pdf(pdf_path: str) -> dict[str, Any]:
    """Extract text from a PDF file using pypdf.

    Reads all pages and returns the combined text content.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        Dict with 'ok', 'text' (str), and 'pages' (int) keys.
    """
    try:
        path = Path(pdf_path)
        if not path.exists():
            return {"ok": False, "error": f"PDF not found: {pdf_path}"}

        if path.suffix.lower() != ".pdf":
            return {"ok": False, "error": f"Not a PDF file: {pdf_path}"}

        try:
            from pypdf import PdfReader
        except ImportError:
            return {
                "ok": False,
                "error": "pypdf package not installed. Run: pip install pypdf>=4.0",
            }

        reader = PdfReader(str(path))
        num_pages = len(reader.pages)

        text_parts: list[str] = []
        for i, page in enumerate(reader.pages):
            try:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(f"--- Page {i + 1} ---\n{page_text}")
            except Exception as page_err:
                text_parts.append(f"--- Page {i + 1} --- [Error: {page_err}]")

        full_text = "\n\n".join(text_parts)

        # Truncate very large PDFs
        if len(full_text) > 50000:
            full_text = full_text[:50000] + "\n\n... (truncated, PDF too large)"

        logger.info("Read PDF '%s': %d pages, %d chars", pdf_path, num_pages, len(full_text))
        return {
            "ok": True,
            "text": full_text,
            "pages": num_pages,
        }

    except Exception as e:
        logger.error("PDF read failed for '%s': %s", pdf_path, e)
        return {"ok": False, "error": f"PDF read failed: {e}"}


def transcribe_audio(audio_path: str) -> dict[str, Any]:
    """Transcribe an audio file using the Groq Whisper API.

    Supports wav, mp3, m4a, flac, ogg, and webm formats.

    Args:
        audio_path: Path to the audio file.

    Returns:
        Dict with 'ok' and 'text' (transcription) keys.
    """
    try:
        path = Path(audio_path)
        if not path.exists():
            return {"ok": False, "error": f"Audio file not found: {audio_path}"}

        # Check supported formats
        supported = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"}
        if path.suffix.lower() not in supported:
            return {
                "ok": False,
                "error": f"Unsupported audio format: {path.suffix}. Supported: {supported}",
            }

        # Check file size (Groq limit is ~25MB)
        file_size = path.stat().st_size
        if file_size > 25 * 1024 * 1024:
            return {"ok": False, "error": "Audio file too large (max 25MB)"}

        groq_key = os.getenv("GROQ_API_KEY", "")
        if not groq_key:
            return {"ok": False, "error": "GROQ_API_KEY not set for audio transcription"}

        # Send to Groq Whisper API
        with httpx.Client(timeout=120) as client:
            with open(path, "rb") as audio_file:
                response = client.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {groq_key}"},
                    data={"model": "whisper-large-v3"},
                    files={"file": (path.name, audio_file, "audio/mpeg")},
                )
                response.raise_for_status()
                data = response.json()

        text = data.get("text", "")

        logger.info("Transcribed audio '%s': %d chars", audio_path, len(text))
        return {
            "ok": True,
            "text": text,
        }

    except httpx.HTTPStatusError as e:
        logger.error("Groq Whisper API error: %s", e)
        return {"ok": False, "error": f"Transcription API error: HTTP {e.response.status_code}"}
    except Exception as e:
        logger.error("Audio transcription failed for '%s': %s", audio_path, e)
        return {"ok": False, "error": f"Transcription failed: {e}"}


# ============================================================================
# Auto-register all multimodal tools
# ============================================================================


register_tool(
    name="analyze_image",
    function=analyze_image,
    description=(
        "Analyse an image file using a vision AI model. "
        "Returns a text description or answer to a question about the image."
    ),
    parameters={
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "Path to the image file (jpg, png, gif, webp)",
            },
            "question": {
                "type": "string",
                "description": "Optional question about the image",
                "default": "",
            },
        },
        "required": ["image_path"],
    },
)


register_tool(
    name="read_pdf",
    function=read_pdf,
    description="Extract text content from a PDF file. Returns the full text and page count.",
    parameters={
        "type": "object",
        "properties": {
            "pdf_path": {
                "type": "string",
                "description": "Path to the PDF file to read",
            },
        },
        "required": ["pdf_path"],
    },
)


register_tool(
    name="transcribe_audio",
    function=transcribe_audio,
    description=(
        "Transcribe an audio file to text using Groq Whisper API. "
        "Supports wav, mp3, m4a, flac, ogg, and webm formats."
    ),
    parameters={
        "type": "object",
        "properties": {
            "audio_path": {
                "type": "string",
                "description": "Path to the audio file to transcribe",
            },
        },
        "required": ["audio_path"],
    },
)
