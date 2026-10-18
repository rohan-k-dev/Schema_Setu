"""
Canonical FarmerProfile model.

This is the single source of truth for farmer profile data.
All components (LangGraph state, API responses, frontend) use these field names.

Values are canonicalised deterministically on construction (Phase 7, BUG-004/017):
  - state      → canonical Indian state / UT name ("karnataka", "KA" → "Karnataka");
                 values that are not an Indian state/UT are dropped
  - primary_crop → corpus crop vocabulary ("paddy" → "rice", "moongfali" → "groundnut")
  - category   → General / OBC / SC / ST / EWS
  - gender     → male / female / other
  - numbers    → negative, NaN and infinite values are dropped (never stored)
Invalid values become None (unknown) so the assistant asks again instead of
reasoning over bad data.
"""

import math
from typing import Any, ClassVar, List, Optional

from pydantic import BaseModel, Field, field_validator

INDIAN_STATES = [
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat",
    "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh",
    "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan",
    "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep", "Puducherry",
]
_STATE_BY_LOWER = {s.lower(): s for s in INDIAN_STATES}
_STATE_EXTRA_ALIASES = {"new delhi": "Delhi", "nct of delhi": "Delhi", "pondicherry": "Puducherry",
                        "west bengal state": "West Bengal", "j and k": "Jammu and Kashmir"}

# Synonym → corpus crop vocabulary (data/validated/schemes.json uses these names).
_CROP_CANONICAL = {
    "paddy": "rice", "dhan": "rice", "chawal": "rice", "nel": "rice",
    "gehun": "wheat", "gehu": "wheat",
    "makka": "maize", "corn": "maize", "makki": "maize",
    "finger millet": "ragi", "nachni": "ragi", "nachani": "ragi", "mandua": "ragi", "mandia": "ragi",
    "moongfali": "groundnut", "mungfali": "groundnut", "peanut": "groundnut",
    "sarson": "mustard", "soyabean": "soybean", "soya": "soybean",
    "kapas": "cotton", "ganna": "sugarcane", "jowar": "sorghum", "bajra": "pearl millet",
    "arhar": "tur", "toor": "tur",
}
_CATEGORY_CANONICAL = {
    "general": "General", "gen": "General", "open": "General",
    "obc": "OBC", "other backward class": "OBC", "other backward classes": "OBC",
    "sc": "SC", "scheduled caste": "SC", "scheduled castes": "SC", "dalit": "SC",
    "st": "ST", "scheduled tribe": "ST", "scheduled tribes": "ST", "tribal": "ST", "adivasi": "ST",
    "ews": "EWS", "economically weaker section": "EWS", "economically weaker sections": "EWS",
}
_GENDER_CANONICAL = {"m": "male", "male": "male", "man": "male",
                     "f": "female", "female": "female", "woman": "female", "women": "female",
                     "other": "other", "transgender": "other"}


def canonical_state(value: Any) -> Optional[str]:
    """Canonical state/UT name, or None when the value is not an Indian state/UT."""
    if value is None:
        return None
    from app.eligibility.normalizer import normalize_state  # approved alias table (KA, MH, ...)
    s = " ".join(str(value).strip().split()).lower()
    if not s:
        return None
    if s in _STATE_EXTRA_ALIASES:
        return _STATE_EXTRA_ALIASES[s]
    return _STATE_BY_LOWER.get(s) or _STATE_BY_LOWER.get(normalize_state(s) or "")


def _finite_non_negative(value: Any) -> Optional[float]:
    from app.eligibility.normalizer import safe_parse_numeric
    return safe_parse_numeric(value)


class FarmerProfile(BaseModel):
    """
    Structured farmer demographic and agricultural data.
    All fields are Optional because information is gathered incrementally
    through conversation.
    """
    farmer_id: Optional[str] = None
    state: Optional[str] = None
    district: Optional[str] = None
    land_size_acres: Optional[float] = None
    primary_crop: Optional[str] = None
    annual_income: Optional[float] = None
    category: Optional[str] = Field(None, description="General, OBC, SC, ST, EWS")
    gender: Optional[str] = None
    has_aadhaar: Optional[bool] = None
    occupation: Optional[str] = Field(None, description="e.g. farmer (required by several schemes)")
    age: Optional[int] = Field(None, description="Age in years (required by PM-KMY, PMJJBY, PMSBY)")

    # Critical fields for completeness checking (class constant, not a profile field)
    CRITICAL_FIELDS: ClassVar[List[str]] = ["state", "land_size_acres", "primary_crop"]

    model_config = {"extra": "ignore"}

    # ─── deterministic canonicalisation / validation ──────────────

    @field_validator("state", mode="before")
    @classmethod
    def _v_state(cls, v):
        return canonical_state(v)

    @field_validator("district", "occupation", mode="before")
    @classmethod
    def _v_text(cls, v):
        if v is None:
            return None
        s = " ".join(str(v).strip().split())
        return s or None

    @field_validator("occupation", mode="after")
    @classmethod
    def _v_occupation(cls, v):
        return v.lower() if v else v

    @field_validator("primary_crop", mode="before")
    @classmethod
    def _v_crop(cls, v):
        if v is None:
            return None
        s = " ".join(str(v).strip().split()).lower()
        return _CROP_CANONICAL.get(s, s) or None

    @field_validator("category", mode="before")
    @classmethod
    def _v_category(cls, v):
        if v is None:
            return None
        s = " ".join(str(v).strip().split()).lower()
        return _CATEGORY_CANONICAL.get(s)

    @field_validator("gender", mode="before")
    @classmethod
    def _v_gender(cls, v):
        if v is None:
            return None
        return _GENDER_CANONICAL.get(str(v).strip().lower())

    @field_validator("land_size_acres", "annual_income", mode="before")
    @classmethod
    def _v_number(cls, v):
        return _finite_non_negative(v)

    @field_validator("age", mode="before")
    @classmethod
    def _v_age(cls, v):
        n = _finite_non_negative(v)
        if n is None or not (0 < n < 120):
            return None
        return int(n)

    @field_validator("has_aadhaar", mode="before")
    @classmethod
    def _v_bool(cls, v):
        if v is None or isinstance(v, bool):
            return v
        s = str(v).strip().lower()
        if s in ("true", "yes", "1", "haan", "ha"):
            return True
        if s in ("false", "no", "0", "nahi", "nhi"):
            return False
        return None

    def get_missing_critical_fields(self) -> list[str]:
        """
        Return a deterministic, priority-ordered list of missing critical fields.
        Order: state → land_size_acres → primary_crop
        """
        missing = []
        for field_name in self.CRITICAL_FIELDS:
            value = getattr(self, field_name, None)
            if value is None:
                missing.append(field_name)
        return missing

    def merge_with(self, new_data: "FarmerProfile") -> "FarmerProfile":
        """
        Merge new extraction data into the existing profile.
        Only non-None fields from new_data overwrite existing values.
        Existing non-None values are never erased by None.
        """
        current_dict = self.model_dump()
        new_dict = new_data.model_dump(exclude_none=True)

        # Only overwrite with actual new values
        for key, value in new_dict.items():
            current_dict[key] = value

        return FarmerProfile(**current_dict)
