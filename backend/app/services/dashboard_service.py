"""
Dashboard eligibility — every active scheme checked against the farmer's SAVED profile.

Eligibility is decided only by the deterministic engine (app.eligibility), never by
the LLM. Each result carries a "basis" (profile version + fingerprint of the scheme
records and rules + engine version); the dashboard compares it with the current
basis to show when a result is stale and needs recalculating.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.database.repositories.rule_repository import RuleRepository
from app.database.repositories.scheme_repository import SchemeRepository
from app.eligibility.models import ELIGIBILITY_ENGINE_VERSION, EligibilityStatus
from app.models.dashboard_schemas import (
    DashboardSchemeResult,
    EligibilityBasis,
    EligibilityDashboard,
    MissingDetail,
    ProfileConflict,
    SavedStatusChange,
)
from app.services.chat_profile_service import CHAT_PROFILE_FIELDS
from app.services.eligibility_service import evaluate_candidate_schemes
from app.services.profile_service import get_farmer_saved_schemes, get_profile

STATUSES = [s.value for s in EligibilityStatus]

# Engine field → (profile field the farmer edits, label)
_EDITABLE = {
    "has_land": ("land_size", "Land size"),
    "land_size_acres": ("land_size", "Land size"),
    "state": ("state", "State"),
    "district": ("district", "District"),
    "primary_crop": ("primary_crop", "Main crop"),
    "occupation": ("occupation", "Occupation"),
    "age": ("age", "Age"),
    "gender": ("gender", "Gender"),
    "category": ("category", "Social category"),
    "residence": ("residence", "Rural or urban"),
}

_INCOME_AT_LEAST_8_LAKH = {"above_10_lakh"}


class DashboardUnavailable(Exception):
    """Scheme data could not be loaded (database down)."""


async def _load_corpus() -> Tuple[list, Dict[str, list], str, int]:
    """Active schemes, their rules, a fingerprint of both, and the rule count."""
    try:
        schemes = await SchemeRepository.list_active()
        rules = await RuleRepository.list_for_scheme_ids([s.scheme_id for s in schemes])
    except Exception as exc:
        raise DashboardUnavailable(type(exc).__name__) from exc

    material = [
        {
            "scheme": [s.scheme_id, s.name, s.status, s.data_version, s.official_url,
                       s.updated_at.isoformat() if s.updated_at else None],
            "rules": [
                [r.field_name, r.operator, r.value_json, r.logical_group, r.required,
                 r.unit, r.rule_order]
                for r in rules.get(s.scheme_id, [])
            ],
        }
        for s in sorted(schemes, key=lambda s: s.scheme_id)
    ]
    blob = json.dumps(material, sort_keys=True, default=str, separators=(",", ":"))
    fingerprint = hashlib.sha256(blob.encode()).hexdigest()
    return schemes, rules, fingerprint, sum(len(v) for v in rules.values())


def _basis(profile, fingerprint: str, scheme_count: int, rule_count: int) -> EligibilityBasis:
    return EligibilityBasis(
        profile_version=profile.version if profile else None,
        profile_updated_at=profile.updated_at if profile else None,
        data_fingerprint=fingerprint,
        engine_version=ELIGIBILITY_ENGINE_VERSION,
        scheme_count=scheme_count,
        rule_count=rule_count,
    )


async def get_basis(farmer_id: str) -> EligibilityBasis:
    """The current basis — cheap enough to poll for staleness."""
    profile = await get_profile(farmer_id)
    schemes, _, fingerprint, rule_count = await _load_corpus()
    return _basis(profile, fingerprint, len(schemes), rule_count)


def engine_profile(profile) -> Dict[str, Any]:
    """The saved profile as the engine sees it: known values only (unknown stays unknown)."""
    if profile is None:
        return {}
    return {f: getattr(profile, f) for f in CHAT_PROFILE_FIELDS if getattr(profile, f) is not None}


def profile_conflicts(profile) -> List[ProfileConflict]:
    """Deterministic consistency checks on saved details."""
    out = []
    if profile and profile.category == "EWS" and profile.income_range in _INCOME_AT_LEAST_8_LAKH:
        out.append(ProfileConflict(
            fields=["category", "income_range"],
            message=("EWS category needs a family income below ₹8 lakh a year, but your income "
                     "range is above ₹10 lakh. Please correct your category or income range."),
        ))
    return out


def _status_note(status: str, has_rules: bool) -> Optional[str]:
    if status != EligibilityStatus.UNVERIFIABLE.value:
        return None
    if not has_rules:
        return "This scheme has no checkable eligibility rules yet. Please check the official website."
    return "This scheme's rules are under review, so eligibility can't be confirmed automatically."


async def _schemes_under_review(farmer_id: str) -> set:
    """Schemes with an open review case raised by this farmer's own searches (shown, never decided here)."""
    try:
        from app.services import profile_service, review_workflow
        farmer = await profile_service.profile_repo.get_farmer_by_farmer_id(farmer_id)
        return await review_workflow.open_scheme_ids_for_farmer(farmer.id) if farmer else set()
    except Exception:
        return set()


async def compute_dashboard(
    farmer_id: str,
    status_filter: Optional[str] = None,
    page: int = 1,
    page_size: int = 10,
) -> EligibilityDashboard:
    profile = await get_profile(farmer_id)
    schemes, rules, fingerprint, rule_count = await _load_corpus()
    candidates = [{"scheme_id": s.scheme_id, "name": s.name, "official_url": s.official_url}
                  for s in schemes]
    urls = {s.scheme_id: s.official_url for s in schemes}

    ranked = await evaluate_candidate_schemes(candidates, rules, engine_profile(profile))
    saved = {s.scheme_id: s for s in await get_farmer_saved_schemes(farmer_id)}
    under_review = await _schemes_under_review(farmer_id)

    counts = {s: 0 for s in STATUSES}
    results: List[DashboardSchemeResult] = []
    missing: Dict[str, dict] = {}
    for r in ranked:
        status = r.eligibility_status.value
        counts[status] += 1
        er = r.eligibility_result or {}
        s = saved.get(r.scheme_id)
        results.append(DashboardSchemeResult(
            scheme_id=r.scheme_id,
            scheme_name=r.scheme_name,
            status=status,
            rank=r.rank,
            reasons=r.rank_reasons,
            matched_criteria=er.get("matched_criteria", []),
            failed_criteria=er.get("failed_criteria", []),
            missing_criteria=er.get("missing_criteria", []),
            explanation=r.explanation,
            status_note=_status_note(status, bool(rules.get(r.scheme_id))),
            official_url=urls.get(r.scheme_id),
            saved=s is not None,
            saved_status=s.eligibility_status if s else None,
            status_changed_since_saved=bool(s and s.eligibility_status
                                            and s.eligibility_status != status),
            under_review=r.scheme_id in under_review,
        ))
        if status == EligibilityStatus.NEEDS_MORE_INFORMATION.value:
            for field in er.get("missing_information", []):
                edit_field, label = _EDITABLE.get(field, (field, field.replace("_", " ").title()))
                entry = missing.setdefault(edit_field, {"label": label, "schemes": []})
                if r.scheme_name not in entry["schemes"]:
                    entry["schemes"].append(r.scheme_name)

    missing_details = sorted(
        (MissingDetail(field=f, label=v["label"], scheme_count=len(v["schemes"]),
                       schemes=v["schemes"][:5]) for f, v in missing.items()),
        key=lambda m: (-m.scheme_count, m.field),
    )
    changes = [
        SavedStatusChange(scheme_id=x.scheme_id, scheme_name=x.scheme_name,
                          saved_status=x.saved_status, current_status=x.status)
        for x in results if x.status_changed_since_saved
    ]

    filtered = [x for x in results if not status_filter or x.status == status_filter]
    start = (page - 1) * page_size
    return EligibilityDashboard(
        basis=_basis(profile, fingerprint, len(schemes), rule_count),
        computed_at=datetime.now(timezone.utc).isoformat(),
        has_profile=profile is not None,
        counts=counts,
        status_filter=status_filter,
        total=len(filtered),
        page=page,
        page_size=page_size,
        items=filtered[start:start + page_size],
        missing_details=missing_details,
        conflicts=profile_conflicts(profile),
        saved_status_changes=changes,
    )
