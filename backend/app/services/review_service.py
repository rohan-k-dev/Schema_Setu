"""
Review Service — Human-in-the-Loop escalation (§56–§67).

Manages the review queue for cases that cannot be reliably
resolved by the automated eligibility engine.

This is implemented as a controlled project simulation (§67):
cases are stored in-memory for academic demonstration.
In production, this would use PostgreSQL.

IMPORTANT: Human review must NOT silently change the canonical database (§64).
"""

from typing import Dict, List, Optional
from datetime import datetime

from app.models.review import (
    ReviewCase, ReviewAuditEntry, ReviewStatus, ReviewReason,
    ReviewAction, is_valid_transition, SENSITIVE_FIELDS,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

# ═══════════════════════════════════════════════════════════════
# IN-MEMORY REVIEW QUEUE (§67 — academic demonstration)
# ═══════════════════════════════════════════════════════════════
_review_cases: Dict[str, ReviewCase] = {}
_audit_log: List[ReviewAuditEntry] = []


# ═══════════════════════════════════════════════════════════════
# ESCALATION TRIGGERS (§57)
# ═══════════════════════════════════════════════════════════════

def _status_value(status) -> str:
    return getattr(status, "value", status) or ""


def should_escalate(
    eligibility_results: list,
    source_conflicts: list,
    retrieval_errors: dict,
) -> Optional[ReviewReason]:
    """
    Determine if a case should be escalated to human review (§57).

    Uses explicit deterministic triggers — NOT vague LLM judgment.

    Returns:
        ReviewReason if escalation needed, None otherwise.
    """
    # 1. Conflicting scheme rules — checked first: a rule conflict also makes the
    #    status UNVERIFIABLE, and the more specific reason must win (BUG-005)
    for result in eligibility_results:
        if getattr(result, "conflicts", None):
            return ReviewReason.RULE_CONFLICT

    # 2. UNVERIFIABLE eligibility (compare the enum *value*: str() of a str-Enum
    #    is "EligibilityStatus.UNVERIFIABLE" on Python 3.11, BUG-005)
    for result in eligibility_results:
        if _status_value(getattr(result, "status", None)) == "UNVERIFIABLE":
            return ReviewReason.UNVERIFIABLE

    # 3. Source conflicts
    if source_conflicts:
        return ReviewReason.SOURCE_CONFLICT

    # 4. System errors across multiple retrieval channels
    error_count = sum(1 for v in retrieval_errors.values() if v)
    if error_count >= 2:
        return ReviewReason.SYSTEM_ERROR

    return None


def create_review_case(
    session_id: str,
    query: str,
    reason: ReviewReason,
    profile: dict,
    scheme_ids: List[str],
    eligibility_results: list,
    source_conflicts: list,
) -> ReviewCase:
    """
    Create a new review case and add to queue (§58).

    Automatically strips sensitive fields (§61).
    """
    # Sanitize profile — strip Aadhaar, bank info etc.
    safe_profile = {
        k: v for k, v in profile.items()
        if k not in SENSITIVE_FIELDS
    }

    # Convert eligibility results to dicts for serialization
    elig_dicts = []
    for r in eligibility_results:
        if hasattr(r, "__dict__"):
            elig_dicts.append({
                "scheme_id": getattr(r, "scheme_id", ""),
                "status": _status_value(getattr(r, "status", "")),
                "missing_information": getattr(r, "missing_information", []),
            })
        elif isinstance(r, dict):
            elig_dicts.append(r)

    case = ReviewCase(
        session_id=session_id,
        reason=reason,
        query=query,
        profile_snapshot=safe_profile,
        scheme_ids=scheme_ids,
        eligibility_results=elig_dicts,
        source_conflicts=[
            c if isinstance(c, dict) else {"conflict": str(c)}
            for c in source_conflicts
        ],
    )

    _review_cases[case.case_id] = case

    # Audit entry
    _audit_log.append(ReviewAuditEntry(
        case_id=case.case_id,
        action="CREATED",
        note=f"Auto-escalated: {reason.value}",
    ))

    logger.info(f"Review case created: {case.case_id} reason={reason.value}")
    return case


def escalate_if_needed(
    session_id: str,
    query: str,
    profile: dict,
    eligibility_results: list,
    source_conflicts: list,
    retrieval_errors: dict,
) -> Optional[ReviewCase]:
    """
    Pipeline entry point (Phase 7 BUG-005): evaluate the deterministic triggers
    and open a review case. At most one open (PENDING/IN_REVIEW) case per
    session and reason, so repeated searches do not flood the queue.
    Never changes eligibility results or canonical data (§64).
    """
    reason = should_escalate(eligibility_results, source_conflicts, retrieval_errors or {})
    if reason is None:
        return None

    for case in _review_cases.values():
        if (case.session_id == session_id and case.reason == reason
                and case.status in (ReviewStatus.PENDING, ReviewStatus.IN_REVIEW)):
            return case

    if reason == ReviewReason.RULE_CONFLICT:
        triggering = [r for r in eligibility_results if getattr(r, "conflicts", None)]
    elif reason == ReviewReason.UNVERIFIABLE:
        triggering = [r for r in eligibility_results
                      if _status_value(getattr(r, "status", None)) == "UNVERIFIABLE"]
    else:
        triggering = list(eligibility_results)
    scheme_ids = [getattr(r, "scheme_id", "") for r in triggering]
    return create_review_case(
        session_id=session_id or "unknown",
        query=(query or "")[:500],
        reason=reason,
        profile=dict(profile or {}),
        scheme_ids=scheme_ids,
        eligibility_results=triggering,
        source_conflicts=source_conflicts or [],
    )


# ═══════════════════════════════════════════════════════════════
# QUERY
# ═══════════════════════════════════════════════════════════════

def get_all_cases(
    status_filter: Optional[ReviewStatus] = None,
) -> List[ReviewCase]:
    """Get all review cases, optionally filtered by status."""
    cases = list(_review_cases.values())
    if status_filter:
        cases = [c for c in cases if c.status == status_filter]
    return sorted(cases, key=lambda c: c.created_at, reverse=True)


def get_case(case_id: str) -> Optional[ReviewCase]:
    """Get a single review case by ID."""
    return _review_cases.get(case_id)


# ═══════════════════════════════════════════════════════════════
# REVIEWER ACTIONS (§63)
# ═══════════════════════════════════════════════════════════════

def resolve_case(
    case_id: str,
    action: ReviewAction,
    reviewer_id: str = "admin",
    note: str = "",
) -> Optional[ReviewCase]:
    """
    Resolve a review case (§63, §65).

    Validates status transition (§125).
    Stores reviewer decision + note + timestamp (§65).

    Returns:
        Updated case, or None if invalid.
    """
    case = _review_cases.get(case_id)
    if not case:
        logger.warning(f"Review case not found: {case_id}")
        return None

    # Determine target status from action
    if action in (ReviewAction.APPROVE, ReviewAction.REJECT):
        target_status = ReviewStatus.RESOLVED
    elif action == ReviewAction.MARK_UNVERIFIABLE:
        target_status = ReviewStatus.RESOLVED
    elif action == ReviewAction.REQUEST_INFORMATION:
        target_status = ReviewStatus.IN_REVIEW
    else:
        target_status = ReviewStatus.RESOLVED

    # Validate transition (§125)
    if not is_valid_transition(case.status, target_status):
        logger.warning(
            f"Invalid transition: {case.status.value} → {target_status.value} "
            f"for case {case_id}"
        )
        return None

    # Update case
    case.status = target_status
    case.reviewer_id = reviewer_id
    case.reviewer_action = action.value
    case.reviewer_note = note
    case.reviewed_at = datetime.utcnow().isoformat()

    # Audit entry (§70, §126)
    _audit_log.append(ReviewAuditEntry(
        case_id=case_id,
        action=action.value,
        reviewer=reviewer_id,
        note=note,
    ))

    logger.info(
        f"Review case {case_id}: {action.value} by {reviewer_id}"
    )
    return case


def dismiss_case(
    case_id: str,
    reviewer_id: str = "admin",
    note: str = "",
) -> Optional[ReviewCase]:
    """Dismiss a review case (§125)."""
    case = _review_cases.get(case_id)
    if not case:
        return None

    if not is_valid_transition(case.status, ReviewStatus.DISMISSED):
        return None

    case.status = ReviewStatus.DISMISSED
    case.reviewer_id = reviewer_id
    case.reviewer_note = note
    case.reviewed_at = datetime.utcnow().isoformat()

    _audit_log.append(ReviewAuditEntry(
        case_id=case_id,
        action="DISMISSED",
        reviewer=reviewer_id,
        note=note,
    ))

    return case


def get_audit_log(case_id: Optional[str] = None) -> List[ReviewAuditEntry]:
    """Get audit log entries, optionally filtered by case ID (§70)."""
    if case_id:
        return [e for e in _audit_log if e.case_id == case_id]
    return list(_audit_log)


def get_queue_stats() -> Dict:
    """Get review queue statistics."""
    cases = list(_review_cases.values())
    return {
        "total": len(cases),
        "pending": sum(1 for c in cases if c.status == ReviewStatus.PENDING),
        "in_review": sum(1 for c in cases if c.status == ReviewStatus.IN_REVIEW),
        "resolved": sum(1 for c in cases if c.status == ReviewStatus.RESOLVED),
        "dismissed": sum(1 for c in cases if c.status == ReviewStatus.DISMISSED),
    }
