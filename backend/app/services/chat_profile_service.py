"""Load saved farmer details into chat and persist consented extractions."""

from typing import Any, Optional

from app.models.auth_schemas import ProfileUpdateRequest
from app.services.profile_service import get_profile, update_profile

CHAT_PROFILE_FIELDS = (
    "state",
    "district",
    "land_size_acres",
    "primary_crop",
    "other_crops",
    "farming_type",
    "age",
    "gender",
    "category",
    "annual_income",
    "has_aadhaar",
    "occupation",
)


async def load_saved_chat_profile(
    farmer_id: Optional[str],
) -> tuple[dict[str, Any], bool]:
    """Return saved profile fields and their persisted consent status."""
    if not farmer_id:
        return {}, False

    profile = await get_profile(farmer_id)
    if profile is None:
        return {}, False

    return (
        {
            field: getattr(profile, field)
            for field in CHAT_PROFILE_FIELDS
            if getattr(profile, field) is not None
        },
        profile.consent_given,
    )


def merge_chat_profiles(
    current: Optional[dict[str, Any]],
    saved: dict[str, Any],
) -> dict[str, Any]:
    """Fill missing chat values from the saved profile without overwriting chat updates."""
    merged = dict(current or {})
    for field, value in saved.items():
        if merged.get(field) is None:
            merged[field] = value
    return merged


async def save_chat_profile(
    farmer_id: Optional[str],
    profile: Optional[dict[str, Any]],
    *,
    consent_to_save: bool,
    existing_consent: bool,
) -> bool:
    """Persist extracted details only when the farmer has explicitly consented."""
    if not farmer_id or not profile:
        return False
    if not consent_to_save and not existing_consent:
        return False

    profile_data = {
        field: profile[field]
        for field in CHAT_PROFILE_FIELDS
        if profile.get(field) is not None
    }
    request = ProfileUpdateRequest(
        **profile_data,
        consent_given=consent_to_save or existing_consent,
    )
    updated = await update_profile(farmer_id, request)
    if updated is None:
        raise RuntimeError("Profile update did not return a saved profile.")
    return True
