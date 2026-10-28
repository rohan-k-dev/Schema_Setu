"""
Centralized Language Registry — Phase 6 (§8, §9).

Single source of truth for all supported languages.
No hardcoded language codes throughout the application.

Each language declares its actual service support level:
  SUPPORTED         — fully functional
  PARTIALLY_SUPPORTED — some services work (e.g. text but not TTS)
  UNAVAILABLE        — not available
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class SupportLevel(str, Enum):
    """Language feature support level (§9)."""
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class LanguageConfig:
    """Configuration for a single language (§8)."""
    code: str                    # Internal code e.g. "en"
    name: str                    # Native name e.g. "English"
    english_name: str            # English name
    sarvam_code: str             # Sarvam API code e.g. "en-IN"
    asr_support: SupportLevel    # Speech-to-text availability
    tts_support: SupportLevel    # Text-to-speech availability
    translation_support: SupportLevel  # Translation availability
    ui_support: SupportLevel     # Frontend UI labels available
    script: str = ""             # Script name e.g. "Devanagari"
    bcp47: str = ""              # BCP47 tag e.g. "en-IN"


# ═══════════════════════════════════════════════════════════════
# LANGUAGE REGISTRY — actual Sarvam-supported languages (§9)
# ═══════════════════════════════════════════════════════════════
# Based on actual Sarvam AI API capabilities.
# Do NOT claim support without verification (§9).

LANGUAGE_REGISTRY: Dict[str, LanguageConfig] = {
    "en": LanguageConfig(
        code="en",
        name="English",
        english_name="English",
        sarvam_code="en-IN",
        bcp47="en-IN",
        script="Latin",
        asr_support=SupportLevel.SUPPORTED,
        tts_support=SupportLevel.SUPPORTED,
        translation_support=SupportLevel.SUPPORTED,
        ui_support=SupportLevel.SUPPORTED,
    ),
    "hi": LanguageConfig(
        code="hi",
        name="हिन्दी",
        english_name="Hindi",
        sarvam_code="hi-IN",
        bcp47="hi-IN",
        script="Devanagari",
        asr_support=SupportLevel.SUPPORTED,
        tts_support=SupportLevel.SUPPORTED,
        translation_support=SupportLevel.SUPPORTED,
        ui_support=SupportLevel.SUPPORTED,
    ),
    "kn": LanguageConfig(
        code="kn",
        name="ಕನ್ನಡ",
        english_name="Kannada",
        sarvam_code="kn-IN",
        bcp47="kn-IN",
        script="Kannada",
        asr_support=SupportLevel.SUPPORTED,
        tts_support=SupportLevel.SUPPORTED,
        translation_support=SupportLevel.SUPPORTED,
        ui_support=SupportLevel.SUPPORTED,
    ),
    "ta": LanguageConfig(
        code="ta",
        name="தமிழ்",
        english_name="Tamil",
        sarvam_code="ta-IN",
        bcp47="ta-IN",
        script="Tamil",
        asr_support=SupportLevel.SUPPORTED,
        tts_support=SupportLevel.SUPPORTED,
        translation_support=SupportLevel.SUPPORTED,
        ui_support=SupportLevel.SUPPORTED,
    ),
    "te": LanguageConfig(
        code="te",
        name="తెలుగు",
        english_name="Telugu",
        sarvam_code="te-IN",
        bcp47="te-IN",
        script="Telugu",
        asr_support=SupportLevel.SUPPORTED,
        tts_support=SupportLevel.SUPPORTED,
        translation_support=SupportLevel.SUPPORTED,
        ui_support=SupportLevel.SUPPORTED,
    ),
    "mr": LanguageConfig(
        code="mr",
        name="मराठी",
        english_name="Marathi",
        sarvam_code="mr-IN",
        bcp47="mr-IN",
        script="Devanagari",
        asr_support=SupportLevel.SUPPORTED,
        tts_support=SupportLevel.SUPPORTED,
        translation_support=SupportLevel.SUPPORTED,
        ui_support=SupportLevel.SUPPORTED,
    ),
    "bn": LanguageConfig(
        code="bn",
        name="বাংলা",
        english_name="Bengali",
        sarvam_code="bn-IN",
        bcp47="bn-IN",
        script="Bengali",
        asr_support=SupportLevel.SUPPORTED,
        tts_support=SupportLevel.SUPPORTED,
        translation_support=SupportLevel.SUPPORTED,
        ui_support=SupportLevel.SUPPORTED,
    ),
    "gu": LanguageConfig(
        code="gu",
        name="ગુજરાતી",
        english_name="Gujarati",
        sarvam_code="gu-IN",
        bcp47="gu-IN",
        script="Gujarati",
        asr_support=SupportLevel.SUPPORTED,
        tts_support=SupportLevel.SUPPORTED,
        translation_support=SupportLevel.SUPPORTED,
        ui_support=SupportLevel.SUPPORTED,
    ),
    "od": LanguageConfig(
        code="od",
        name="ଓଡ଼ିଆ",
        english_name="Odia",
        sarvam_code="od-IN",
        bcp47="or-IN",
        script="Odia",
        asr_support=SupportLevel.SUPPORTED,
        tts_support=SupportLevel.SUPPORTED,
        translation_support=SupportLevel.SUPPORTED,
        ui_support=SupportLevel.SUPPORTED,
    ),
    "pa": LanguageConfig(
        code="pa",
        name="ਪੰਜਾਬੀ",
        english_name="Punjabi",
        sarvam_code="pa-IN",
        bcp47="pa-IN",
        script="Gurmukhi",
        asr_support=SupportLevel.SUPPORTED,
        tts_support=SupportLevel.SUPPORTED,
        translation_support=SupportLevel.SUPPORTED,
        ui_support=SupportLevel.PARTIALLY_SUPPORTED,
    ),
    "ml": LanguageConfig(
        code="ml",
        name="മലയാളം",
        english_name="Malayalam",
        sarvam_code="ml-IN",
        bcp47="ml-IN",
        script="Malayalam",
        asr_support=SupportLevel.SUPPORTED,
        tts_support=SupportLevel.SUPPORTED,
        translation_support=SupportLevel.SUPPORTED,
        ui_support=SupportLevel.PARTIALLY_SUPPORTED,
    ),
}

# ─── Internal processing language (§15) ────────────────────────
INTERNAL_LANGUAGE = "en"

# ─── Default fallback ──────────────────────────────────────────
DEFAULT_LANGUAGE = "en"


# ═══════════════════════════════════════════════════════════════
# LOOKUP HELPERS
# ═══════════════════════════════════════════════════════════════

def get_language(code: str) -> Optional[LanguageConfig]:
    """Get language config by internal code (e.g. 'hi', 'kn')."""
    return LANGUAGE_REGISTRY.get(code)


def get_language_by_sarvam_code(sarvam_code: str) -> Optional[LanguageConfig]:
    """Get language config by Sarvam code (e.g. 'hi-IN')."""
    for lang in LANGUAGE_REGISTRY.values():
        if lang.sarvam_code == sarvam_code:
            return lang
    return None


def get_sarvam_code(code: str) -> str:
    """Get Sarvam API code for an internal code. Falls back to en-IN."""
    lang = LANGUAGE_REGISTRY.get(code)
    return lang.sarvam_code if lang else "en-IN"


def get_supported_languages() -> List[LanguageConfig]:
    """Get all languages with at least partial support."""
    return [
        lang for lang in LANGUAGE_REGISTRY.values()
        if lang.ui_support != SupportLevel.UNAVAILABLE
    ]


def get_language_for_frontend() -> List[Dict]:
    """
    Get language list formatted for frontend selector (§11).
    Returns: [{code, name, english_name, has_voice, has_tts}]
    """
    result = []
    for lang in get_supported_languages():
        result.append({
            "code": lang.code,
            "name": lang.name,
            "english_name": lang.english_name,
            "has_voice": lang.asr_support == SupportLevel.SUPPORTED,
            "has_tts": lang.tts_support == SupportLevel.SUPPORTED,
        })
    return result


def is_supported_language(code: str) -> bool:
    """Check if a language code is in the registry."""
    return code in LANGUAGE_REGISTRY


def resolve_language_code(code: str) -> str:
    """
    Resolve a language code to a valid internal code.
    Handles both short ('hi') and Sarvam ('hi-IN') formats.
    Falls back to DEFAULT_LANGUAGE.
    """
    if code in LANGUAGE_REGISTRY:
        return code
    # Try extracting from Sarvam-style code
    short = code.split("-")[0].lower()
    if short in LANGUAGE_REGISTRY:
        return short
    return DEFAULT_LANGUAGE
