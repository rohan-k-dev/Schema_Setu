"""
Normalizer — converts raw scheme data into canonical form.

Normalizes: state names, crop names, categories, genders, whitespace, URLs.
Preserves original source values for traceability.
"""

import re
from typing import Optional, List
from urllib.parse import urlparse

from app.ingestion.constants import (
    CANONICAL_STATES, STATE_ALIASES,
    CANONICAL_CROPS, CROP_ALIASES,
    CANONICAL_CATEGORIES, CATEGORY_ALIASES,
    CANONICAL_GENDERS, GENDER_ALIASES,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


def normalize_state(value: str) -> Optional[str]:
    """Normalize a state name to canonical form."""
    if not value:
        return None
    cleaned = value.strip()
    # Check exact match first
    for state in CANONICAL_STATES:
        if cleaned.lower() == state.lower():
            return state
    # Check aliases
    alias_key = cleaned.lower().strip()
    if alias_key in STATE_ALIASES:
        return STATE_ALIASES[alias_key]
    # Return original if no match (don't silently drop)
    logger.warning(f"Could not normalize state: '{value}'")
    return cleaned


def normalize_states(values: List[str]) -> List[str]:
    """Normalize a list of state names."""
    result = []
    for v in values:
        normalized = normalize_state(v)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def normalize_crop(value: str) -> Optional[str]:
    """Normalize a crop name to canonical form."""
    if not value:
        return None
    cleaned = value.strip().lower()
    if cleaned in CANONICAL_CROPS:
        return cleaned
    if cleaned in CROP_ALIASES:
        return CROP_ALIASES[cleaned]
    logger.debug(f"Could not normalize crop: '{value}'")
    return cleaned


def normalize_crops(values: List[str]) -> List[str]:
    """Normalize a list of crop names."""
    result = []
    for v in values:
        normalized = normalize_crop(v)
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def normalize_category(value: str) -> Optional[str]:
    """Normalize a social category to canonical form."""
    if not value:
        return None
    cleaned = value.strip().lower()
    if cleaned in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[cleaned]
    for cat in CANONICAL_CATEGORIES:
        if cleaned == cat.lower():
            return cat
    return value.strip()


def normalize_gender(value: str) -> str:
    """Normalize gender to canonical form."""
    if not value:
        return "unknown"
    cleaned = value.strip().lower()
    if cleaned in CANONICAL_GENDERS:
        return cleaned
    if cleaned in GENDER_ALIASES:
        return GENDER_ALIASES[cleaned]
    return "unknown"


def normalize_whitespace(text: str) -> str:
    """Clean up whitespace in text."""
    if not text:
        return ""
    # Replace multiple spaces/newlines with single space
    cleaned = re.sub(r'\s+', ' ', text)
    return cleaned.strip()


def normalize_url(url: str) -> Optional[str]:
    """Validate and normalize a URL."""
    if not url or not url.strip():
        return None
    url = url.strip()
    # Must be http or https
    if not url.startswith(("http://", "https://")):
        return None
    try:
        parsed = urlparse(url)
        if not parsed.hostname:
            return None
        return url
    except Exception:
        return None


def validate_url_format(url: str) -> bool:
    """Check if a URL has valid format."""
    if not url:
        return False
    try:
        parsed = urlparse(url)
        return bool(parsed.scheme in ("http", "https") and parsed.hostname)
    except Exception:
        return False


def generate_scheme_id(name: str, level: str = "", state: str = "") -> str:
    """
    Generate a stable, deterministic scheme ID from the scheme name.

    Rules:
    - Uppercase
    - Replace spaces/hyphens with underscores
    - Remove special characters
    - Prepend STATE_ for state-level schemes
    """
    if not name:
        raise ValueError("Cannot generate ID from empty name")

    # Clean the name
    cleaned = name.strip()
    # Remove common prefixes
    cleaned = re.sub(r'^(Pradhan Mantri|PM|National|Rashtriya)\s+', '', cleaned, flags=re.IGNORECASE)
    # Replace spaces and hyphens
    cleaned = re.sub(r'[\s\-]+', '_', cleaned)
    # Remove non-alphanumeric (except underscore)
    cleaned = re.sub(r'[^A-Za-z0-9_]', '', cleaned)
    # Uppercase
    cleaned = cleaned.upper()

    # Truncate if too long
    if len(cleaned) > 40:
        cleaned = cleaned[:40]

    # Remove trailing underscores
    cleaned = cleaned.rstrip('_')

    # Add state prefix for state schemes
    if level == "state" and state:
        state_code = state[:2].upper()
        return f"STATE_{state_code}_{cleaned}"

    return cleaned
