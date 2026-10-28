"""
Which language is the farmer actually using? (reply and speak in it, whatever the language picker says)

- Voice: Sarvam's speech-to-text-translate detects the spoken language (e.g. "hi-IN").
- Text: the script decides — Devanagari → Hindi (or Marathi when Marathi is selected), Kannada script →
  Kannada, and so on. Latin-script text keeps the selected language, so romanised Hindi ("mujhe yojana
  batao") still works when Hindi is selected, and English stays English.
"""

from __future__ import annotations

import re
from typing import Dict, Optional

from app.localization.languages import LANGUAGE_REGISTRY, resolve_language_code

# Unicode blocks of the scripts SchemeSetu supports
_SCRIPTS: Dict[str, str] = {
    "devanagari": r"ऀ-ॿ", "bengali": r"ঀ-৿", "gurmukhi": r"਀-੿",
    "gujarati": r"઀-૿", "odia": r"଀-୿", "tamil": r"஀-௿",
    "telugu": r"ఀ-౿", "kannada": r"ಀ-೿", "malayalam": r"ഀ-ൿ",
}
_SCRIPT_LANGUAGE = {"bengali": "bn", "gurmukhi": "pa", "gujarati": "gu", "odia": "od", "tamil": "ta",
                    "telugu": "te", "kannada": "kn", "malayalam": "ml"}
_DEVANAGARI_LANGUAGES = ("hi", "mr")
_LATIN = re.compile(r"[A-Za-z]")
_COUNTERS = {name: re.compile(f"[{rng}]") for name, rng in _SCRIPTS.items()}


def detect_text_language(text: str, selected: str) -> str:
    """Language of a typed message: its dominant Indian script, else the selected language."""
    selected = resolve_language_code(selected or "en")
    counts = {name: len(rx.findall(text or "")) for name, rx in _COUNTERS.items()}
    script, n = max(counts.items(), key=lambda kv: kv[1])
    if n == 0 or n < len(_LATIN.findall(text or "")):
        return selected                                   # Latin-script (English or romanised)
    if script == "devanagari":
        return selected if selected in _DEVANAGARI_LANGUAGES else "hi"
    lang = _SCRIPT_LANGUAGE[script]
    return lang if lang in LANGUAGE_REGISTRY else selected


def spoken_language(detected: Optional[str], selected: str) -> str:
    """Language Sarvam heard ("hi-IN" → "hi") when it's one we support, else the selected one."""
    if detected:
        code = resolve_language_code(detected)
        if code in LANGUAGE_REGISTRY and detected.split("-")[0].lower() == code:
            return code
    return resolve_language_code(selected or "en")
