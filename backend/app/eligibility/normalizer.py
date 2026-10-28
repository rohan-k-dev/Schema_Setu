"""
Field normalizer — canonical value normalization for eligibility evaluation.

Normalizes both user profile values and rule values before comparison (§15, §84).
Uses only explicitly approved mappings — never invents (§15, §501).
"""

import math
import re
from typing import Optional, Any, Union

# ─── State normalization (§16) ────────────────────────────────

_STATE_ALIASES = {
    "ka": "karnataka", "kar": "karnataka", "karnatak": "karnataka",
    "mh": "maharashtra", "maha": "maharashtra",
    "ap": "andhra pradesh", "andhra": "andhra pradesh",
    "ts": "telangana", "tel": "telangana",
    "tn": "tamil nadu", "tamilnadu": "tamil nadu",
    "up": "uttar pradesh",
    "mp": "madhya pradesh",
    "wb": "west bengal",
    "rj": "rajasthan", "raj": "rajasthan",
    "gj": "gujarat", "guj": "gujarat",
    "pb": "punjab",
    "hr": "haryana",
    "hp": "himachal pradesh",
    "jk": "jammu and kashmir", "j&k": "jammu and kashmir",
    "uk": "uttarakhand",
    "or": "odisha", "orissa": "odisha",
    "ke": "kerala",
    "ga": "goa",
    "br": "bihar",
    "jh": "jharkhand",
    "ch": "chhattisgarh", "chattisgarh": "chhattisgarh",
    "as": "assam",
    "mn": "manipur",
    "ml": "meghalaya",
    "mz": "mizoram",
    "nl": "nagaland",
    "sk": "sikkim",
    "tr": "tripura",
    "ar": "arunachal pradesh",
}

# ─── Crop normalization (§18) ────────────────────────────────

_CROP_ALIASES = {
    "finger millet": "ragi",
    "nachni": "ragi",
    "mandua": "ragi",
    "paddy": "rice",
    "dhan": "rice",
    "chawal": "rice",
    "gehun": "wheat",
    "gehu": "wheat",
    "makka": "maize",
    "corn": "maize",
    "moong": "moong dal",
    "urad": "urad dal",
    "arhar": "tur dal",
    "toor": "tur dal",
    "groundnut": "peanut",
    "moongfali": "peanut",
    "mustard": "sarson",
    "sugarcane": "sugarcane",
    "ganna": "sugarcane",
    "cotton": "cotton",
    "kapas": "cotton",
    "soyabean": "soybean",
    "jowar": "sorghum",
    "bajra": "pearl millet",
}

# ─── Category normalization (§19) ────────────────────────────

_CATEGORY_ALIASES = {
    "scheduled caste": "sc",
    "scheduled tribe": "st",
    "other backward class": "obc",
    "other backward classes": "obc",
    "economically weaker section": "ews",
    "economically weaker sections": "ews",
    "general": "general",
    "gen": "general",
}


def normalize_string(value: Any) -> Optional[str]:
    """Normalize a string value: lowercase, strip, collapse whitespace."""
    if value is None:
        return None
    s = str(value).strip().lower()
    s = re.sub(r'\s+', ' ', s)
    return s if s else None


def normalize_state(value: Any) -> Optional[str]:
    """Normalize state name using approved aliases (§16)."""
    s = normalize_string(value)
    if s is None:
        return None
    return _STATE_ALIASES.get(s, s)


def normalize_crop(value: Any) -> Optional[str]:
    """Normalize crop name using approved aliases (§18)."""
    s = normalize_string(value)
    if s is None:
        return None
    return _CROP_ALIASES.get(s, s)


def normalize_category(value: Any) -> Optional[str]:
    """Normalize social category using approved aliases (§19)."""
    s = normalize_string(value)
    if s is None:
        return None
    return _CATEGORY_ALIASES.get(s, s)


def normalize_gender(value: Any) -> Optional[str]:
    """Normalize gender value."""
    s = normalize_string(value)
    if s is None:
        return None
    if s in ("m", "male", "man"):
        return "male"
    if s in ("f", "female", "woman", "women"):
        return "female"
    if s in ("other", "transgender"):
        return "other"
    return s


def safe_parse_numeric(value: Any) -> Optional[float]:
    """
    Safely parse a numeric value (§23, §188).

    Handles commas, currency signs, lakh/crore notation.
    Returns None for unparseable, negative or non-finite values — never
    silently returns 0. Negative land/income is invalid (§184) whether it
    arrives as a number or as a string.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        val = float(value)
    else:
        s = str(value).strip()
        if not s:
            return None

        # Remove currency symbols and commas
        s = s.replace("₹", "").replace("Rs.", "").replace("Rs", "")
        s = s.replace(",", "").strip()

        # Lakh / crore notation (§189): "1.5 lakh", "2 lakhs", "3 lac" → 150000 / 200000 / 300000
        multiplier = 1.0
        unit_match = re.match(r'^([\d.]+)\s*(lakhs?|lacs?|crores?)\s*$', s, re.IGNORECASE)
        if unit_match:
            s = unit_match.group(1)
            multiplier = 1e7 if unit_match.group(2).lower().startswith("crore") else 1e5

        try:
            val = float(s) * multiplier
        except (ValueError, TypeError):
            return None

    if not math.isfinite(val) or val < 0:
        return None
    return val


def normalize_field_value(field_name: str, value: Any) -> Any:
    """Normalize a profile/rule value based on field type (§15)."""
    if value is None:
        return None

    if field_name == "state":
        return normalize_state(value)
    elif field_name == "district":
        return normalize_string(value)
    elif field_name in ("primary_crop", "crop"):
        return normalize_crop(value)
    elif field_name == "category":
        return normalize_category(value)
    elif field_name == "gender":
        return normalize_gender(value)
    elif field_name in ("land_size_acres", "annual_income", "age"):
        return safe_parse_numeric(value)
    elif field_name in ("has_aadhaar",):
        if isinstance(value, bool):
            return value
        s = normalize_string(value)
        if s in ("true", "yes", "1", "haan", "ha"):
            return True
        if s in ("false", "no", "0", "nahi", "nhi"):
            return False
        return None
    elif field_name == "occupation":
        return normalize_string(value)
    else:
        return value


def normalize_rule_value(field_name: str, value: Any) -> Any:
    """Normalize a rule's comparison value using the same normalizer."""
    if isinstance(value, list):
        return [normalize_field_value(field_name, v) for v in value]
    return normalize_field_value(field_name, value)
