"""
Validation utilities.

Common validation functions for request data.
"""

from typing import Optional, Tuple

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Supported audio MIME types
SUPPORTED_AUDIO_TYPES = {
    "audio/webm",
    "audio/webm;codecs=opus",
    "audio/ogg",
    "audio/ogg;codecs=opus",
    "audio/wav",
    "audio/wave",
    "audio/x-wav",
    "audio/mp4",
    "audio/mpeg",
    "audio/mp3",
    "audio/flac",
}

# Map MIME types to file extensions
MIME_TO_EXTENSION = {
    "audio/webm": ".webm",
    "audio/webm;codecs=opus": ".webm",
    "audio/ogg": ".ogg",
    "audio/ogg;codecs=opus": ".ogg",
    "audio/wav": ".wav",
    "audio/wave": ".wav",
    "audio/x-wav": ".wav",
    "audio/mp4": ".mp4",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/flac": ".flac",
}


def _sniff_audio_family(header: bytes) -> Optional[str]:
    """Identify the audio container from its magic bytes (None if not recognised)."""
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WAVE":
        return "wav"
    if header[:4] == bytes([0x1A, 0x45, 0xDF, 0xA3]):  # EBML (WebM / Matroska)
        return "webm"
    if header[:4] == b"OggS":
        return "ogg"
    if header[:4] == b"fLaC":
        return "flac"
    if len(header) >= 8 and header[4:8] == b"ftyp":
        return "mp4"
    if header[:3] == b"ID3" or (len(header) >= 2 and header[0] == 0xFF and (header[1] & 0xE0) == 0xE0):
        return "mp3"
    return None


_MIME_FAMILY = {
    "audio/webm": "webm", "audio/ogg": "ogg", "audio/wav": "wav", "audio/wave": "wav",
    "audio/x-wav": "wav", "audio/mp4": "mp4", "audio/mpeg": "mp3", "audio/mp3": "mp3",
    "audio/flac": "flac",
}


def validate_audio_upload(
    content_type: Optional[str],
    file_size: int,
    filename: Optional[str] = None,
    header: Optional[bytes] = None,
) -> Tuple[bool, Optional[str]]:
    """
    Validate an audio file upload.

    When `header` (the first bytes of the file) is given, the content must be
    a recognised audio container matching the declared MIME type, so non-audio
    payloads are rejected before they reach the ASR provider (§109, BUG-024).

    Returns (is_valid, error_message).
    """
    # Check file size
    max_bytes = int(settings.MAX_AUDIO_SIZE_MB * 1024 * 1024)
    if file_size <= 0:
        return False, "Empty audio file. Please record again."
    if file_size > max_bytes:
        return False, f"Audio file too large. Maximum size is {settings.MAX_AUDIO_SIZE_MB}MB."

    # Check content type
    if not content_type:
        return False, "Audio file type could not be determined."

    # Normalize content type (strip parameters like charset)
    normalized_type = content_type.lower().strip()

    if normalized_type not in SUPPORTED_AUDIO_TYPES:
        # Also check without codec parameters
        base_type = normalized_type.split(";")[0].strip()
        if base_type not in SUPPORTED_AUDIO_TYPES:
            return False, f"Unsupported audio format: {content_type}. Supported: WAV, WebM, OGG, MP3, MP4, FLAC."

    if header is not None:
        family = _sniff_audio_family(header)
        declared = _MIME_FAMILY.get(normalized_type.split(";")[0].strip())
        if family is None:
            return False, "The uploaded file is not a recognised audio recording. Please record again."
        if declared and declared != family and not {declared, family} <= {"webm", "ogg"}:
            return False, "The audio content does not match its declared format. Please record again."

    return True, None


def get_audio_extension(content_type: str) -> str:
    """Get the correct file extension for an audio MIME type."""
    normalized = content_type.lower().strip()
    return MIME_TO_EXTENSION.get(normalized, ".webm")
