"""PAGAL OS Voice Agent Interface — speech-to-text and text-to-speech.

Uses:
    - STT: Groq Whisper API (via httpx POST to the OpenAI-compatible endpoint)
    - TTS: edge-tts (free, no API key) for text-to-speech

The full pipeline: audio in -> transcribe -> run agent -> synthesize -> audio out.
"""

import asyncio
import io
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("pagal_os")

# Default configuration (overridable via config.yaml)
DEFAULT_STT_API_BASE = "https://api.groq.com/openai/v1"
DEFAULT_STT_MODEL = "whisper-large-v3-turbo"
DEFAULT_TTS_VOICE = "en-US-AriaNeural"


def _get_voice_config() -> dict[str, str]:
    """Load voice configuration from config.yaml.

    Returns:
        Dict with stt_api_key, stt_api_base, stt_model, tts_voice.
    """
    config: dict[str, str] = {
        "stt_api_key": os.getenv("STT_API_KEY", ""),
        "stt_api_base": DEFAULT_STT_API_BASE,
        "stt_model": DEFAULT_STT_MODEL,
        "tts_voice": DEFAULT_TTS_VOICE,
    }

    try:
        import yaml
        from pathlib import Path

        config_path = Path(__file__).parent.parent.parent / "config.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            voice_cfg = data.get("voice", {})
            if isinstance(voice_cfg, dict):
                config["stt_api_key"] = voice_cfg.get("stt_api_key", config["stt_api_key"])
                config["stt_api_base"] = voice_cfg.get("stt_api_base", config["stt_api_base"])
                config["stt_model"] = voice_cfg.get("stt_model", config["stt_model"])
                config["tts_voice"] = voice_cfg.get("tts_voice", config["tts_voice"])
    except Exception as e:
        logger.debug("Failed to load voice config: %s", e)

    # Resolve env var placeholders like ${STT_API_KEY}
    for key, val in config.items():
        if isinstance(val, str) and val.startswith("${") and val.endswith("}"):
            env_name = val[2:-1]
            config[key] = os.getenv(env_name, "")

    return config


# ---------------------------------------------------------------------------
# Speech-to-Text (STT)
# ---------------------------------------------------------------------------


def transcribe_audio(audio_bytes: bytes) -> str:
    """Transcribe audio bytes to text via Groq Whisper API.

    Args:
        audio_bytes: Raw audio data (WAV, OGG, MP3, etc.).

    Returns:
        Transcribed text string.

    Raises:
        RuntimeError: If STT_API_KEY is not configured or API call fails.
    """
    try:
        cfg = _get_voice_config()
        api_key = cfg["stt_api_key"]
        if not api_key:
            raise RuntimeError(
                "STT_API_KEY not configured. Set it in .env or config.yaml."
            )

        url = f"{cfg['stt_api_base']}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {api_key}"}

        # Send as multipart form data
        files = {
            "file": ("audio.ogg", io.BytesIO(audio_bytes), "audio/ogg"),
        }
        data = {
            "model": cfg["stt_model"],
            "response_format": "text",
        }

        with httpx.Client(timeout=30) as client:
            resp = client.post(url, headers=headers, files=files, data=data)
            resp.raise_for_status()
            text = resp.text.strip()

        logger.info("Transcribed audio: %s", text[:100])
        return text
    except RuntimeError:
        raise
    except Exception as e:
        logger.error("STT transcription failed: %s", e)
        raise RuntimeError(f"Transcription failed: {e}") from e


# ---------------------------------------------------------------------------
# Text-to-Speech (TTS)
# ---------------------------------------------------------------------------


def synthesize_speech(text: str, voice: str | None = None) -> bytes:
    """Convert text to speech audio via edge-tts.

    Args:
        text: Text to convert to speech.
        voice: Voice name (default: from config or en-US-AriaNeural).

    Returns:
        MP3 audio bytes.

    Raises:
        RuntimeError: If edge-tts is not installed or synthesis fails.
    """
    try:
        import edge_tts  # type: ignore[import-untyped]
    except ImportError as e:
        raise RuntimeError(
            "edge-tts is not installed. Run: pip install edge-tts"
        ) from e

    try:
        cfg = _get_voice_config()
        voice = voice or cfg["tts_voice"]

        # edge-tts is async, so we need to run in an event loop
        async def _synthesize() -> bytes:
            """Run edge-tts communicate and collect audio bytes."""
            communicate = edge_tts.Communicate(text, voice)
            audio_chunks: list[bytes] = []
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_chunks.append(chunk["data"])
            return b"".join(audio_chunks)

        # Use existing loop if available, otherwise create one
        try:
            loop = asyncio.get_running_loop()
            # If we're already in an async context, create a task
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                audio_bytes = pool.submit(
                    lambda: asyncio.run(_synthesize())
                ).result(timeout=30)
        except RuntimeError:
            # No running event loop — safe to use asyncio.run
            audio_bytes = asyncio.run(_synthesize())

        logger.info("Synthesized speech: %d bytes for text: %s", len(audio_bytes), text[:60])
        return audio_bytes
    except RuntimeError:
        raise
    except Exception as e:
        logger.error("TTS synthesis failed: %s", e)
        raise RuntimeError(f"Speech synthesis failed: {e}") from e


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


def process_voice_message(
    audio_bytes: bytes,
    agent_name: str,
) -> tuple[str, bytes]:
    """Full voice pipeline: transcribe -> run agent -> synthesize response.

    Args:
        audio_bytes: Raw audio data from the user.
        agent_name: Name of the agent to route the message to.

    Returns:
        Tuple of (text_response, audio_response_bytes).
    """
    try:
        # Step 1: Transcribe audio to text
        user_text = transcribe_audio(audio_bytes)
        if not user_text:
            return ("I couldn't understand the audio.", b"")

        # Step 2: Run the agent
        from src.core.runtime import load_agent, run_agent

        agent = load_agent(agent_name)
        result = run_agent(agent, user_text)

        if result.ok:
            text_response = result.output or "(Empty response from agent)"
        else:
            text_response = f"Agent error: {result.error}"

        # Step 3: Synthesize response to audio
        try:
            audio_response = synthesize_speech(text_response)
        except Exception as tts_err:
            logger.warning("TTS failed, returning text-only: %s", tts_err)
            audio_response = b""

        return (text_response, audio_response)
    except Exception as e:
        logger.error("Voice pipeline failed: %s", e)
        error_msg = f"Voice processing error: {e}"
        return (error_msg, b"")
