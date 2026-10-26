"""
Profile service — business logic for farmer profile management,
saved schemes, search history, and the personalized dashboard.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from app.core.logging import get_logger
from app.database.repositories import profile_repository as profile_repo
from app.database.repositories import search_history_repository as history_repo
from app.database.repositories.farmer_repository import (
    get_farmer_by_id,
    get_farmer_pk,
    get_farmer_profile,
    get_saved_schemes,
)
from app.models.auth_schemas import (
    AccountResponse,
    DashboardResponse,
    ProfileResponse,
    ProfileUpdateRequest,
    SavedSchemeResponse,
    SearchHistoryEntry,
)
from app.models.profile import FarmerProfile

logger = get_logger(__name__)

# Critical fields for profile completeness scoring
_CRITICAL_FIELDS = ["state", "primary_crop", "land_size_acres"]
# Fields the eligibility engine / scheme search use (Aadhaar status and exact income
# are deliberately not collected — no eligibility rule needs them).
_ALL_PROFILE_FIELDS = [
    "state", "district", "land_size_acres", "primary_crop",
    "age", "gender", "category", "income_range", "occupation", "residence",
]


class ProfileError(Exception):
    """Raised for profile-layer errors."""
    def __init__(self, message: str, code: str = "PROFILE_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


# ─── Profile ──────────────────────────────────────────────────────────────────
#
# Every operation is keyed by the authenticated farmer_id (from the session), which
# is resolved to the account PK here; request bodies can never name another account.

# Land units farmers use, converted to acres for the eligibility engine.
# (Bigha is not offered: its size differs from state to state.)
ACRES_PER_UNIT = {"acre": 1.0, "hectare": 2.47105, "guntha": 0.025, "cent": 0.01}

# Fields copied as-is from the validated request to the database.
_DIRECT_FIELDS = ("state", "district", "other_crops", "farming_type", "age", "gender",
                  "category", "income_range", "residence")


def land_to_acres(value: Optional[float], unit: Optional[str]) -> Optional[float]:
    if value is None or unit is None:
        return None
    return round(value * ACRES_PER_UNIT[unit], 4)


def income_to_range(amount: Optional[float]) -> Optional[str]:
    """Coarse income band for an exact amount (exact incomes are not stored)."""
    if amount is None:
        return None
    for limit, band in ((100_000, "below_1_lakh"), (250_000, "1_to_2.5_lakh"),
                        (500_000, "2.5_to_5_lakh"), (1_000_000, "5_to_10_lakh")):
        if amount < limit:
            return band
    return "above_10_lakh"


def _changes_from_request(req: ProfileUpdateRequest) -> dict:
    """Columns to write: only fields the client sent; null means 'set to unknown'."""
    sent = req.model_fields_set - {"consent_given", "expected_version"}
    changes: dict = {f: getattr(req, f) for f in _DIRECT_FIELDS if f in sent}
    if "land_size" in sent:
        changes["land_size_value"] = req.land_size
        changes["land_unit"] = req.land_unit if req.land_size is not None else None
        changes["land_size_acres"] = land_to_acres(req.land_size, req.land_unit)
    if "primary_crop" in sent:
        changes["primary_crop"] = (FarmerProfile(primary_crop=req.primary_crop).primary_crop
                                   if req.primary_crop is not None else None)
    if "occupation" in sent:
        changes["occupation"] = req.occupation.lower() if req.occupation is not None else None
    return changes


async def get_profile(farmer_id: str) -> Optional[ProfileResponse]:
    """Return the authenticated farmer's saved profile, or None."""
    farmer = await profile_repo.get_farmer_by_farmer_id(farmer_id)
    if not farmer:
        return None
    row = await profile_repo.get_profile(farmer.id)
    return _build_profile_response(farmer.farmer_id, farmer.email, farmer.full_name, row)


async def update_profile(farmer_id: str, req: ProfileUpdateRequest) -> ProfileResponse:
    """
    Save a partial update of the authenticated farmer's profile.

    - Consent must be given (req.consent_given) before the first save.
    - Fields left out keep their value; fields sent as null become unknown.
    - With req.expected_version, a save based on an outdated copy (e.g. the profile
      was changed meanwhile in chat or on another device) raises CONFLICT (HTTP 409).
    """
    farmer = await profile_repo.get_farmer_by_farmer_id(farmer_id)
    if not farmer:
        raise ProfileError("Farmer account not found.", "NOT_FOUND")
    existing = await profile_repo.get_profile(farmer.id)

    consent_already = bool(existing and existing.consent_given)
    if not req.consent_given and not consent_already:
        raise ProfileError(
            "Consent is required before saving personal data. "
            "Please check the consent checkbox and try again.",
            "CONSENT_REQUIRED",
        )

    changes = _changes_from_request(req)
    if req.consent_given and not consent_already:
        changes["consent_given"] = True
        changes["consent_given_at"] = datetime.now(tz=timezone.utc)

    try:
        row = await profile_repo.save_profile(farmer.id, changes, req.expected_version)
    except profile_repo.VersionConflict:
        raise ProfileError(
            "Your profile was changed somewhere else (for example in the chat or on another "
            "device). Reload it, check the values and save again.",
            "CONFLICT",
        )
    return _build_profile_response(farmer.farmer_id, farmer.email, farmer.full_name, row)


# ─── Saved schemes ────────────────────────────────────────────────────────────

async def get_farmer_saved_schemes(farmer_id: str) -> List[SavedSchemeResponse]:
    """Return all saved schemes for the farmer."""
    pk = await get_farmer_pk(farmer_id)
    if not pk:
        return []
    rows = await get_saved_schemes(pk)
    return [_scheme_row_to_response(r) for r in rows]


# Saving, unsaving and checklists: app/services/saved_scheme_service.py


# ─── Search history ───────────────────────────────────────────────────────────

MAX_QUERY_CHARS = 200
# Chat/voice turns that are scheme searches (not follow-up questions or errors)
SEARCH_STATUSES = {"schemes_found", "partial_results", "no_results"}


async def record_search(
    farmer_id: Optional[str],
    query: str,
    results_count: int = 0,
    language: str = "en",
) -> bool:
    """
    Keep a search in the farmer's history, following the retention policy
    (docs/DASHBOARD.md): signed-in farmers who agreed to keep their details only,
    query trimmed to MAX_QUERY_CHARS, at most 50 entries / 90 days.
    Never raises — a history failure must not break the chat. Returns True if stored.
    """
    query = " ".join((query or "").split())[:MAX_QUERY_CHARS]
    if not farmer_id or not query:
        return False
    try:
        pk = await get_farmer_pk(farmer_id)
        profile = await profile_repo.get_profile(pk) if pk else None
        if not profile or not profile.consent_given:
            return False
        await history_repo.add(pk, query, max(0, int(results_count)), (language or "en")[:10])
        return True
    except Exception as exc:
        logger.warning(f"record_search failed (non-fatal): {type(exc).__name__}")
        return False


def _history_entry(r) -> SearchHistoryEntry:
    return SearchHistoryEntry(
        id=r.id,
        query=r.query,
        results_count=r.results_count,
        language=r.language,
        searched_at=r.searched_at.isoformat() if r.searched_at else None,
    )


async def get_farmer_search_history(
    farmer_id: str, limit: int = 10, offset: int = 0,
) -> tuple[List[SearchHistoryEntry], int]:
    """One page of the farmer's recent searches (newest first) and the total count."""
    pk = await get_farmer_pk(farmer_id)
    if not pk:
        return [], 0
    rows, total = await history_repo.list_page(pk, limit, offset)
    return [_history_entry(r) for r in rows], total


async def delete_search(farmer_id: str, entry_id: int) -> bool:
    """Delete one of the farmer's own searches (False if not found / not theirs)."""
    pk = await get_farmer_pk(farmer_id)
    return bool(pk) and await history_repo.delete_one(pk, entry_id)


async def clear_search_history(farmer_id: str) -> int:
    pk = await get_farmer_pk(farmer_id)
    return await history_repo.clear(pk) if pk else 0


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
        recent, _ = await get_farmer_search_history(farmer_id, 10)

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

    def num(v):  # 0 is a real value (e.g. landless); only None means unknown
        return float(v) if v is not None else None

    return ProfileResponse(
        farmer_id=farmer_id,
        full_name=full_name,
        email=email,
        state=profile_row.state,
        district=profile_row.district,
        land_size=num(profile_row.land_size_value),
        land_unit=profile_row.land_unit,
        land_size_acres=num(profile_row.land_size_acres),
        primary_crop=profile_row.primary_crop,
        other_crops=profile_row.other_crops,
        farming_type=profile_row.farming_type,
        occupation=profile_row.occupation,
        age=profile_row.age,
        gender=profile_row.gender,
        category=profile_row.category,
        income_range=profile_row.income_range,
        residence=profile_row.residence,
        consent_given=profile_row.consent_given,
        consent_given_at=profile_row.consent_given_at.isoformat() if profile_row.consent_given_at else None,
        profile_completeness=completeness,
        version=profile_row.version,
        updated_at=profile_row.updated_at.isoformat() if profile_row.updated_at else None,
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
