"""
Profile service — business logic for farmer profile management,
saved schemes, search history, and the personalized dashboard.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from app.core.logging import get_logger
from app.database.repositories.farmer_repository import (
    get_farmer_by_id,
    get_farmer_pk,
    get_farmer_profile,
    upsert_farmer_profile,
    get_saved_schemes,
    save_scheme,
    remove_saved_scheme,
    get_search_history,
    add_search_history,
)
from app.models.auth_schemas import (
    AccountResponse,
    DashboardResponse,
    ProfileResponse,
    ProfileUpdateRequest,
    SavedSchemeResponse,
    SaveSchemeRequest,
    SearchHistoryEntry,
)
from app.models.profile import FarmerProfile, INDIAN_STATES

logger = get_logger(__name__)

# Critical fields for profile completeness scoring
_CRITICAL_FIELDS = ["state", "primary_crop", "land_size_acres"]
_ALL_PROFILE_FIELDS = [
    "state", "district", "land_size_acres", "primary_crop",
    "age", "gender", "category", "annual_income", "has_aadhaar", "occupation",
]


class ProfileError(Exception):
    """Raised for profile-layer errors."""
    def __init__(self, message: str, code: str = "PROFILE_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


# ─── Profile ──────────────────────────────────────────────────────────────────

async def get_profile(farmer_id: str) -> Optional[ProfileResponse]:
    """Return the saved profile for the given farmer, or None."""
    farmer = await get_farmer_by_id(farmer_id)
    if not farmer:
        return None

    pk = await get_farmer_pk(farmer_id)
    if not pk:
        return None

    profile_row = await get_farmer_profile(pk)
    return _build_profile_response(farmer_id, farmer.email, farmer.full_name, profile_row)


async def update_profile(farmer_id: str, req: ProfileUpdateRequest) -> ProfileResponse:
    """
    Persist the farmer profile after validating consent.

    Consent must be explicitly given (req.consent_given = True) on the
    first save. Subsequent saves carry the existing consent forward.
    Raises ProfileError if consent is not given.
    """
    pk = await get_farmer_pk(farmer_id)
    if not pk:
        raise ProfileError("Farmer account not found.", "NOT_FOUND")

    existing = await get_farmer_profile(pk)

    # Enforce consent before first save of personal data
    if not req.consent_given and (existing is None or not existing.consent_given):
        raise ProfileError(
            "Consent is required before saving personal data. "
            "Please check the consent checkbox and try again.",
            "CONSENT_REQUIRED",
        )

    # Canonicalize via existing FarmerProfile validators
    canon = FarmerProfile(
        state=req.state,
        district=req.district,
        land_size_acres=req.land_size_acres,
        primary_crop=req.primary_crop,
        age=req.age,
        gender=req.gender,
        category=req.category,
        annual_income=req.annual_income,
        has_aadhaar=req.has_aadhaar,
        occupation=req.occupation,
    )

    data: dict = {}
    if canon.state is not None:
        data["state"] = canon.state
    if req.district is not None:
        data["district"] = req.district
    if canon.land_size_acres is not None:
        data["land_size_acres"] = canon.land_size_acres
    if canon.primary_crop is not None:
        data["primary_crop"] = canon.primary_crop
    if req.other_crops is not None:
        data["other_crops"] = req.other_crops
    if req.farming_type is not None:
        data["farming_type"] = req.farming_type
    if canon.age is not None:
        data["age"] = canon.age
    if canon.gender is not None:
        data["gender"] = canon.gender
    if canon.category is not None:
        data["category"] = canon.category
    if canon.annual_income is not None:
        data["annual_income"] = canon.annual_income
    if canon.has_aadhaar is not None:
        data["has_aadhaar"] = canon.has_aadhaar
    if canon.occupation is not None:
        data["occupation"] = canon.occupation

    # Consent handling
    consent_was_already_given = existing and existing.consent_given
    if req.consent_given and not consent_was_already_given:
        data["consent_given"] = True
        data["consent_given_at"] = datetime.now(tz=timezone.utc)
    elif consent_was_already_given:
        # Keep existing consent
        data["consent_given"] = True

    data["farmer_id"] = pk

    updated = await upsert_farmer_profile(pk, data)

    farmer = await get_farmer_by_id(farmer_id)
    return _build_profile_response(
        farmer_id,
        farmer.email if farmer else "",
        farmer.full_name if farmer else None,
        updated,
    )


# ─── Saved schemes ────────────────────────────────────────────────────────────

async def get_farmer_saved_schemes(farmer_id: str) -> List[SavedSchemeResponse]:
    """Return all saved schemes for the farmer."""
    pk = await get_farmer_pk(farmer_id)
    if not pk:
        return []
    rows = await get_saved_schemes(pk)
    return [_scheme_row_to_response(r) for r in rows]


async def save_farmer_scheme(farmer_id: str, req: SaveSchemeRequest) -> SavedSchemeResponse:
    """Save or update a bookmarked scheme."""
    pk = await get_farmer_pk(farmer_id)
    if not pk:
        raise ProfileError("Farmer account not found.", "NOT_FOUND")
    row = await save_scheme(
        farmer_pk=pk,
        scheme_id=req.scheme_id,
        scheme_name=req.scheme_name,
        eligibility_status=req.eligibility_status,
        notes=req.notes,
    )
    if not row:
        raise ProfileError("Could not save scheme.", "SAVE_FAILED")
    return _scheme_row_to_response(row)


async def delete_farmer_scheme(farmer_id: str, scheme_id: str) -> bool:
    """Remove a saved scheme. Returns True if deleted."""
    pk = await get_farmer_pk(farmer_id)
    if not pk:
        return False
    return await remove_saved_scheme(pk, scheme_id)


# ─── Search history ───────────────────────────────────────────────────────────

async def record_search(
    farmer_id: str,
    query: str,
    results_count: int = 0,
    language: str = "en",
) -> None:
    """Append a search to the farmer's history (fire-and-forget; non-fatal)."""
    try:
        pk = await get_farmer_pk(farmer_id)
        if pk:
            await add_search_history(pk, query, results_count, language)
    except Exception as exc:
        logger.warning(f"record_search failed (non-fatal): {exc}")


async def get_farmer_search_history(farmer_id: str, limit: int = 10) -> List[SearchHistoryEntry]:
    """Return recent searches for the farmer."""
    pk = await get_farmer_pk(farmer_id)
    if not pk:
        return []
    rows = await get_search_history(pk, limit)
    return [
        SearchHistoryEntry(
            id=r.id,
            query=r.query,
            results_count=r.results_count,
            language=r.language,
            searched_at=r.searched_at.isoformat() if r.searched_at else None,
        )
        for r in rows
    ]


# ─── Dashboard ───────────────────────────────────────────────────────────────

async def get_dashboard(farmer_id: str) -> DashboardResponse:
    """
    Assemble the complete dashboard payload:
      - account info
      - saved profile + completeness
      - missing fields
      - saved schemes
      - recent searches
    """
    farmer = await get_farmer_by_id(farmer_id)
    if not farmer:
        raise ProfileError("Farmer account not found.", "NOT_FOUND")

    account = AccountResponse(
        farmer_id=farmer.farmer_id,
        email=farmer.email,
        full_name=farmer.full_name,
        phone=farmer.phone,
        is_active=farmer.is_active,
        is_verified=farmer.is_verified,
        created_at=farmer.created_at.isoformat() if farmer.created_at else None,
        last_login_at=farmer.last_login_at.isoformat() if farmer.last_login_at else None,
    )

    pk = await get_farmer_pk(farmer_id)
    profile_row = await get_farmer_profile(pk) if pk else None
    profile_resp = _build_profile_response(farmer_id, farmer.email, farmer.full_name, profile_row)
    missing = _missing_fields(profile_row)

    saved = []
    recent = []
    if pk:
        saved_rows = await get_saved_schemes(pk)
        saved = [_scheme_row_to_response(r) for r in saved_rows]
        history_rows = await get_search_history(pk, 10)
        recent = [
            SearchHistoryEntry(
                id=r.id,
                query=r.query,
                results_count=r.results_count,
                language=r.language,
                searched_at=r.searched_at.isoformat() if r.searched_at else None,
            )
            for r in history_rows
        ]

    return DashboardResponse(
        account=account,
        profile=profile_resp,
        missing_fields=missing,
        profile_completeness=profile_resp.profile_completeness if profile_resp else 0.0,
        saved_schemes=saved,
        recent_searches=recent,
    )


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _build_profile_response(
    farmer_id: str,
    email: str,
    full_name: Optional[str],
    profile_row,
) -> Optional[ProfileResponse]:
    if profile_row is None:
        return None
    completeness = _compute_completeness(profile_row)
    return ProfileResponse(
        farmer_id=farmer_id,
        full_name=full_name,
        email=email,
        state=profile_row.state,
        district=profile_row.district,
        land_size_acres=float(profile_row.land_size_acres) if profile_row.land_size_acres else None,
        primary_crop=profile_row.primary_crop,
        other_crops=profile_row.other_crops,
        farming_type=profile_row.farming_type,
        age=profile_row.age,
        gender=profile_row.gender,
        category=profile_row.category,
        annual_income=float(profile_row.annual_income) if profile_row.annual_income else None,
        has_aadhaar=profile_row.has_aadhaar,
        occupation=profile_row.occupation,
        consent_given=profile_row.consent_given,
        consent_given_at=profile_row.consent_given_at.isoformat() if profile_row.consent_given_at else None,
        profile_completeness=completeness,
    )


def compute_completeness(profile_row) -> float:
    """Return a 0–100 completeness score for the profile."""
    if profile_row is None:
        return 0.0
    filled = sum(
        1 for f in _ALL_PROFILE_FIELDS if getattr(profile_row, f, None) is not None
    )
    return round(filled / len(_ALL_PROFILE_FIELDS) * 100, 1)


def missing_fields(profile_row) -> List[str]:
    """Return list of critical fields that are still None."""
    if profile_row is None:
        return list(_CRITICAL_FIELDS)
    return [f for f in _CRITICAL_FIELDS if getattr(profile_row, f, None) is None]


_compute_completeness = compute_completeness
_missing_fields = missing_fields


def _scheme_row_to_response(row) -> SavedSchemeResponse:
    return SavedSchemeResponse(
        id=row.id,
        scheme_id=row.scheme_id,
        scheme_name=row.scheme_name,
        eligibility_status=row.eligibility_status,
        notes=row.notes,
        saved_at=row.saved_at.isoformat() if row.saved_at else None,
    )
