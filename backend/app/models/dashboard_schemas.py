"""Response models for the dashboard's eligibility view (docs/DASHBOARD.md)."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class EligibilityBasis(BaseModel):
    """What a result was computed from. A different basis means the result is stale."""

    profile_version: Optional[int]        # None = no saved profile
    profile_updated_at: Optional[str]
    data_fingerprint: str                 # sha256 of active schemes + their rules
    engine_version: str
    scheme_count: int
    rule_count: int


class DashboardSchemeResult(BaseModel):
    scheme_id: str
    scheme_name: str
    status: str                           # ELIGIBLE / NOT_ELIGIBLE / NEEDS_MORE_INFORMATION / UNVERIFIABLE
    rank: int
    reasons: List[str] = []
    matched_criteria: List[Dict[str, Any]] = []
    failed_criteria: List[Dict[str, Any]] = []
    missing_criteria: List[Dict[str, Any]] = []
    explanation: Optional[str] = None
    status_note: Optional[str] = None     # why a scheme is UNVERIFIABLE
    official_url: Optional[str] = None
    saved: bool = False
    saved_status: Optional[str] = None    # status when bookmarked
    status_changed_since_saved: bool = False
    under_review: bool = False             # an open human-review case from your search (docs/HUMAN_REVIEW.md)


class MissingDetail(BaseModel):
    """A profile detail the engine needs; filling it can change these schemes' status."""

    field: str                            # profile field to edit (e.g. "age", "land_size")
    label: str
    scheme_count: int
    schemes: List[str]                    # scheme names (up to 5)


class ProfileConflict(BaseModel):
    """Saved details that cannot all be true together."""

    fields: List[str]
    message: str


class SavedStatusChange(BaseModel):
    scheme_id: str
    scheme_name: str
    saved_status: Optional[str]
    current_status: str


class EligibilityDashboard(BaseModel):
    basis: EligibilityBasis
    computed_at: str
    has_profile: bool
    counts: Dict[str, int]                # all four statuses, always present
    status_filter: Optional[str]
    total: int                            # results matching the filter
    page: int
    page_size: int
    items: List[DashboardSchemeResult]
    missing_details: List[MissingDetail]
    conflicts: List[ProfileConflict]
    saved_status_changes: List[SavedStatusChange]
