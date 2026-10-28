"""
Language Service — translation abstraction layer (§16, §17).

Clean abstraction over Sarvam Translate API.
No direct Sarvam calls in LangGraph nodes.

Translation is presentation/input normalization only.
It must NOT alter structured profile facts (§17).
"""

import asyncio
from typing import Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.core.exceptions import ExternalServiceError, raise_for_provider_status
from app.localization.languages import (
    INTERNAL_LANGUAGE, DEFAULT_LANGUAGE,
    get_sarvam_code, get_language, resolve_language_code,
)

logger = get_logger(__name__)

SARVAM_TRANSLATE_URL = "https://api.sarvam.ai/translate"


def _validate_sarvam_key() -> str:
    """Validate Sarvam API key availability."""
    if not settings.SARVAM_API_KEY:
        raise ExternalServiceError("Sarvam", "SARVAM_API_KEY not configured.")
    return settings.SARVAM_API_KEY


async def translate_to_internal(
    text: str,
    source_language: str,
) -> str:
    """
    Translate user input to internal canonical language (English) (§15).

    If source is already English, returns as-is.
    If translation fails, returns original text (safe fallback, §30).

    Args:
        text: Input text in source language
        source_language: Internal code (e.g. 'hi', 'kn')

    Returns:
        English translation, or original text on failure.
    """
    source_code = resolve_language_code(source_language)

    # Already in internal language — pass through
    if source_code == INTERNAL_LANGUAGE:
        return text

    try:
        return await _translate(
            text=text,
            source_lang=get_sarvam_code(source_code),
            target_lang=get_sarvam_code(INTERNAL_LANGUAGE),
        )
    except Exception as e:
        logger.warning(f"Translation to internal failed ({source_code}→en): {e}. Using original text.")
        return text


async def translate_from_internal(
    text: str,
    target_language: str,
) -> str:
    """
    Translate internal response to user's native language (§31).

    If target is English, returns as-is.
    If translation fails, returns original English text (§33).

    Args:
        text: English response text
        target_language: Internal code (e.g. 'hi', 'kn')

    Returns:
        Translated text, or original English on failure.
    """
    target_code = resolve_language_code(target_language)

    if target_code == INTERNAL_LANGUAGE:
        return text

    try:
        return await _translate(
            text=text,
            source_lang=get_sarvam_code(INTERNAL_LANGUAGE),
            target_lang=get_sarvam_code(target_code),
        )
    except Exception as e:
        logger.warning(f"Translation from internal failed (en→{target_code}): {e}. Using English text.")
        return text


# Sarvam Translate (mayura:v1) rejects inputs over 1000 characters with HTTP 400.
MAX_TRANSLATE_CHARS = 900
TRANSLATE_CONCURRENCY = 5


def _split_for_translation(text: str, limit: int = MAX_TRANSLATE_CHARS) -> list:
    """Split text into pieces of at most `limit` chars, at line, then sentence, then word breaks."""
    pieces: list = []
    for line in text.split("\n"):
        while len(line) > limit:
            cut = max(line.rfind(". ", 0, limit), line.rfind("? ", 0, limit), line.rfind("! ", 0, limit))
            cut = cut + 1 if cut > 0 else line.rfind(" ", 0, limit)
            if cut <= 0:
                cut = limit
            pieces.append(line[:cut])
            line = line[cut:].lstrip()
        pieces.append(line)
    # Re-pack short lines into chunks so long replies need few API calls.
    chunks, current = [], ""
    for p in pieces:
        candidate = f"{current}\n{p}" if current else p
        if current and len(candidate) > limit:
            chunks.append(current)
            current = p
        else:
            current = candidate
    chunks.append(current)
    return chunks


async def _translate(
    text: str,
    source_lang: str,
    target_lang: str,
) -> str:
    """Translate text of any length, keeping its line layout.

    Sarvam returns one paragraph (line breaks are lost) and rejects input over 1000 chars,
    so multi-line text is translated line by line (long lines split), a few lines at a time.
    """
    if "\n" not in text and len(text) <= MAX_TRANSLATE_CHARS:
        return await _translate_chunk(text, source_lang, target_lang)

    sem = asyncio.Semaphore(TRANSLATE_CONCURRENCY)

    async def one(piece: str) -> str:
        if not piece.strip():
            return piece
        async with sem:
            return await _translate_chunk(piece, source_lang, target_lang)

    out_lines = []
    for line in text.split("\n"):
        pieces = _split_for_translation(line) if len(line) > MAX_TRANSLATE_CHARS else [line]
        out_lines.append(pieces)
    translated = await asyncio.gather(*(one(p) for pieces in out_lines for p in pieces))
    it = iter(translated)
    return "\n".join(" ".join(next(it) for _ in pieces) for pieces in out_lines)


async def _translate_chunk(
    text: str,
    source_lang: str,
    target_lang: str,
) -> str:
    """
    Call Sarvam Translate API.

    Args:
        text: Text to translate
        source_lang: Sarvam language code (e.g. 'hi-IN')
        target_lang: Sarvam language code (e.g. 'en-IN')

    Returns:
        Translated text.

    Raises:
        ExternalServiceError on failure.
    """
    api_key = _validate_sarvam_key()

    payload = {
        "input": text,
        "source_language_code": source_lang,
        "target_language_code": target_lang,
        "speaker_gender": "Male",
        "mode": "formal",
        "model": "mayura:v1",
        "enable_preprocessing": True,
    }
    headers = {
        "api-subscription-key": api_key,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=settings.SARVAM_TIMEOUT) as client:
        try:
            response = await client.post(
                SARVAM_TRANSLATE_URL,
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            translated = data.get("translated_text", "").strip()

            if not translated:
                logger.warning("Sarvam translate returned empty result.")
                return text

            logger.info(
                f"Translation {source_lang}→{target_lang}: "
                f"{len(text)} chars → {len(translated)} chars"
            )
            return translated

        except httpx.TimeoutException:
            logger.error(f"Sarvam translate timed out ({source_lang}→{target_lang})")
            raise ExternalServiceError("Sarvam Translate", "Translation timed out.")
        except httpx.HTTPStatusError as e:
            logger.error(f"Sarvam translate HTTP error: {e.response.status_code}")
            raise_for_provider_status("Sarvam Translate", e.response)
            raise ExternalServiceError("Sarvam Translate", "Translation service error.")
        except Exception as e:
            logger.error(f"Sarvam translate unexpected error: {e}")
            raise ExternalServiceError("Sarvam Translate", "Translation failed.")
