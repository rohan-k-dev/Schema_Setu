"""
Voice Service — abstraction over Sarvam AI voice APIs (ASR + TTS).

Phase 6: Language-aware ASR and TTS with typed output models (§27–§33).
Handles speech-to-text-translate and text-to-speech.
Validates SARVAM_API_KEY before use without crashing at import.
"""

import asyncio
from dataclasses import dataclass
from typing import Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.core.exceptions import ConfigurationError, ExternalServiceError, raise_for_provider_status
from app.localization.languages import get_sarvam_code, DEFAULT_LANGUAGE

logger = get_logger(__name__)

SARVAM_ASR_URL = "https://api.sarvam.ai/speech-to-text-translate"
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"


@dataclass
class ASRResult:
    """Typed ASR output (§28)."""
    text: str
    language: str = ""          # Detected/selected language code
    confidence: Optional[float] = None  # null if unavailable (§28)
    duration_ms: Optional[int] = None


def _validate_sarvam_key() -> str:
    """Validate and return the Sarvam API key."""
    if not settings.SARVAM_API_KEY:
        raise ConfigurationError(
            "SARVAM_API_KEY is not configured. Set it in your .env file."
        )
    return settings.SARVAM_API_KEY


async def transcribe_audio(
    audio_bytes: bytes,
    filename: str,
    content_type: str,
    language_code: str = "",
) -> Optional[ASRResult]:
    """
    Send audio to Sarvam ASR for speech-to-text translation (§27).

    Args:
        audio_bytes: Raw audio file bytes
        filename: Original filename with correct extension
        content_type: MIME type of the audio file
        language_code: Optional language hint (internal code e.g. 'hi')

    Returns:
        ASRResult with transcript and language, or None if empty.

    Raises:
        ConfigurationError: If SARVAM_API_KEY is missing.
        ExternalServiceError: If the Sarvam API call fails.
    """
    api_key = _validate_sarvam_key()

    # Browsers send e.g. "audio/webm;codecs=opus"; Sarvam accepts only the bare type
    # ("audio/webm") and rejects the codecs parameter with HTTP 400.
    base_type = (content_type or "audio/webm").split(";")[0].strip().lower()
    files = {"file": (filename, audio_bytes, base_type)}
    headers = {"api-subscription-key": api_key}

    # Add language hint if provided (helps ASR accuracy)
    data = {}
    if language_code:
        sarvam_code = get_sarvam_code(language_code)
        data["language_code"] = sarvam_code

    async with httpx.AsyncClient(timeout=settings.SARVAM_TIMEOUT) as client:
        try:
            response = await client.post(
                SARVAM_ASR_URL,
                headers=headers,
                files=files,
                data=data if data else None,
            )
            response.raise_for_status()

            resp_data = response.json()
            transcript = resp_data.get("transcript", "").strip()

            if not transcript:
                logger.warning("Sarvam ASR returned empty transcript.")
                return None

            # Build typed result (§28)
            result = ASRResult(
                text=transcript,
                language=resp_data.get("language_code", language_code or ""),
                confidence=resp_data.get("confidence"),
                duration_ms=resp_data.get("duration_ms"),
            )

            logger.info(
                f"Sarvam ASR: {len(transcript)} chars, "
                f"lang={result.language}"
            )
            return result

        except httpx.TimeoutException:
            logger.error("Sarvam ASR request timed out.")
            raise ExternalServiceError("Sarvam ASR", "Speech recognition timed out.")
        except httpx.HTTPStatusError as e:
            logger.error(f"Sarvam ASR HTTP error: {e.response.status_code} - {e.response.text}")
            raise_for_provider_status("Sarvam ASR", e.response)
            raise ExternalServiceError("Sarvam ASR", "Speech recognition service error.")
        except Exception as e:
            logger.error(f"Sarvam ASR unexpected error: {e}")
            raise ExternalServiceError("Sarvam ASR", "Speech processing failed.")


async def generate_speech(
    text: str,
    language_code: str = "hi-IN",
) -> Optional[str]:
    """
    Convert text to speech using Sarvam TTS (§32).

    Args:
        text: The text to convert to speech.
        language_code: Target language code — accepts both internal ('hi')
                       and Sarvam ('hi-IN') formats.

    Returns:
        Base64-encoded audio string, or None if TTS fails.

    Raises:
        ConfigurationError: If SARVAM_API_KEY is missing.
        ExternalServiceError: If the Sarvam API call fails.
    """
    api_key = _validate_sarvam_key()

    # Resolve to Sarvam code if internal code given
    if "-" not in language_code:
        language_code = get_sarvam_code(language_code)

    # Sarvam TTS accepts at most 500 characters per input: speak the reply in pieces
    # (markdown removed, at most TTS_MAX_TOTAL_CHARS) and join the WAV audio.
    chunks = split_for_tts(text)
    if not chunks:
        return None
    if len(chunks) == 1:
        return await _speak_chunk(chunks[0], language_code, api_key)
    audios = await asyncio.gather(*(_speak_chunk(c, language_code, api_key) for c in chunks))
    audios = [a for a in audios if a]
    if not audios:
        return None
    return join_wav_base64(audios)


TTS_MAX_CHARS = 480
TTS_MAX_TOTAL_CHARS = 1000


def split_for_tts(text: str, limit: int = TTS_MAX_CHARS, total: int = TTS_MAX_TOTAL_CHARS) -> list:
    """Plain-text pieces of at most `limit` chars, cut at sentence/line breaks."""
    import re
    plain = re.sub(r"[*#|`_]+", "", text or "")
    plain = re.sub(r"\s*\n\s*", ". ", plain.strip())
    plain = re.sub(r"(\.\s*){2,}", ". ", plain)
    plain = re.sub(r"\s{2,}", " ", plain)[:total]
    sentences = re.split(r"(?<=[.!?।])\s+", plain)
    chunks, current = [], ""
    for s in sentences:
        while len(s) > limit:                       # one very long sentence
            cut = s.rfind(" ", 0, limit)
            if cut <= 0:
                cut = limit
            chunks.append(s[:cut].strip())
            s = s[cut:].strip()
        candidate = f"{current} {s}".strip()
        if current and len(candidate) > limit:
            chunks.append(current)
            current = s
        else:
            current = candidate
    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if c]


def join_wav_base64(audios_b64: list) -> str:
    """Concatenate base64 WAV clips with identical format into one base64 WAV."""
    import base64
    import io
    import wave
    out = io.BytesIO()
    writer = None
    for a in audios_b64:
        with wave.open(io.BytesIO(base64.b64decode(a)), "rb") as r:
            if writer is None:
                writer = wave.open(out, "wb")
                writer.setparams(r.getparams())
            writer.writeframes(r.readframes(r.getnframes()))
    writer.close()
    return base64.b64encode(out.getvalue()).decode()


async def _speak_chunk(tts_text: str, language_code: str, api_key: str) -> Optional[str]:
    """One Sarvam TTS call (input <= 500 chars). Returns base64 WAV or None."""
    payload = {
        "inputs": [tts_text],
        "target_language_code": language_code,
        "speaker": "aditya",
        "pace": 1.0,
        "model": "bulbul:v3",
    }
    headers = {
        "api-subscription-key": api_key,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=settings.SARVAM_TIMEOUT) as client:
        try:
            response = await client.post(SARVAM_TTS_URL, json=payload, headers=headers)
            response.raise_for_status()

            data = response.json()
            audios = data.get("audios", [])

            if not audios:
                logger.warning("Sarvam TTS returned no audio data.")
                return None

            logger.info(f"Sarvam TTS generation successful: lang={language_code}")
            return audios[0]

        except httpx.TimeoutException:
            logger.error("Sarvam TTS request timed out.")
            raise ExternalServiceError("Sarvam TTS", "Text-to-speech timed out.")
        except httpx.HTTPStatusError as e:
            logger.error(f"Sarvam TTS HTTP error: {e.response.status_code} - {e.response.text}")
            raise_for_provider_status("Sarvam TTS", e.response)
            raise ExternalServiceError("Sarvam TTS", "Text-to-speech service error.")
        except Exception as e:
            logger.error(f"Sarvam TTS unexpected error: {e}")
            raise ExternalServiceError("Sarvam TTS", "Text-to-speech failed.")
