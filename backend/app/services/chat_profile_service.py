"""Load saved farmer details into chat and persist consented extractions.

Conflict policy between chat and the saved profile (profile page / other devices):
- When the farmer has agreed to keep their profile in sync (consent), the saved
  profile is the latest truth at the start of every turn, so a correction made on
  the profile page replaces the value this chat session remembered.
- Without that consent, saved values only fill gaps in what the chat already knows.
- After a turn, only the fields the farmer actually changed in this turn are written
  back — never the whole chat profile — so stale chat values cannot overwrite a
  newer correction.
- Aadhaar status is never saved. An exact income mentioned in chat is saved only as
  a coarse income range.
"""

from typing import Any, Optional

from app.models.auth_schemas import ProfileUpdateRequest
from app.services.profile_service import get_profile, income_to_range, update_profile

# Saved-profile fields the eligibility engine / retrieval use, in chat-profile names.
CHAT_PROFILE_FIELDS = (
    "state",
    "district",
    "land_size_acres",
    "primary_crop",
    "occupation",
    "age",
    "gender",
    "category",
    "residence",
)


async def load_saved_chat_profile(
    farmer_id: Optional[str],
) -> tuple[dict[str, Any], bool]:
    """Return saved profile fields (known values only) and their consent status."""
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
    saved_is_authoritative: bool = False,
) -> dict[str, Any]:
    """
    Combine the chat session's profile with the saved one.

    saved_is_authoritative=True (profile synced with consent): saved known values win,
    so profile-page corrections reach the chat. Otherwise saved values only fill gaps.
    Unknown (None) saved values never erase what the chat knows.
    """
    merged = dict(current or {})
    for field, value in saved.items():
        if value is None:
            continue
        if saved_is_authoritative or merged.get(field) is None:
            merged[field] = value
    return merged


def changed_fields(before: Optional[dict[str, Any]], after: Optional[dict[str, Any]]) -> dict[str, Any]:
    """Known values in *after* that differ from *before* (what this turn taught us)."""
    before = before or {}
    return {k: v for k, v in (after or {}).items() if v is not None and before.get(k) != v}


def _to_update_request(values: dict[str, Any], consent: bool) -> Optional[ProfileUpdateRequest]:
    data: dict[str, Any] = {f: values[f] for f in CHAT_PROFILE_FIELDS
                            if f in values and f != "land_size_acres"}
    if "land_size_acres" in values:
        data["land_size"] = values["land_size_acres"]
        data["land_unit"] = "acre"
    if values.get("annual_income") is not None:
        data["income_range"] = income_to_range(values["annual_income"])
    # Keep only values that pass the profile's validation (an odd extracted value is
    # skipped instead of failing the whole save).
    valid: dict[str, Any] = {}
    for key in [k for k in data if k != "land_unit"]:
        candidate = {key: data[key], **({"land_unit": "acre"} if key == "land_size" else {})}
        try:
            ProfileUpdateRequest(**candidate)
            valid.update(candidate)
        except ValueError:
            continue
    if not valid and not consent:
        return None
    return ProfileUpdateRequest(**valid, consent_given=consent)


async def save_chat_profile(
    farmer_id: Optional[str],
    profile: Optional[dict[str, Any]],
    *,
    consent_to_save: bool,
    existing_consent: bool,
    previous: Optional[dict[str, Any]] = None,
) -> bool:
    """
    Persist what the farmer told the assistant — only with consent.

    When consent is given for the first time, every known value is saved; afterwards
    only the fields that changed during this turn (compared with *previous*).
    """
    if not farmer_id or not profile:
        return False
    if not consent_to_save and not existing_consent:
        return False

    if hasattr(profile, "model_dump"):
        profile = profile.model_dump()
    if hasattr(previous, "model_dump"):
        previous = previous.model_dump()

    first_consent = consent_to_save and not existing_consent
    values = ({k: v for k, v in profile.items() if v is not None} if first_consent
              else changed_fields(previous, profile))
    request = _to_update_request(values, consent=consent_to_save or existing_consent)
    if request is None or (not request.model_fields_set - {"consent_given"} and not first_consent):
        return False                                  # nothing new to save this turn
    updated = await update_profile(farmer_id, request)
    if updated is None:
        raise RuntimeError("Profile update did not return a saved profile.")
    return True
