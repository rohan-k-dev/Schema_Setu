"""
Human Review API — Phase 6 (§122–§126).

Simple reviewer endpoints for the human-in-the-loop workflow.
Protected with a simple API key header for development (§68).

IMPORTANT: Reviewers must NOT directly edit schemes or
eligibility_rules from this UI (§64).
"""

import hmac
from typing import Optional

from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel, Field

from app.models.review import ReviewStatus, ReviewAction
from app.services.review_service import (
    get_all_cases, get_case, resolve_case, dismiss_case,
    get_audit_log, get_queue_stats,
)
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/review-cases", tags=["Human Review"])

def _check_reviewer_auth(x_review_key: Optional[str] = Header(None)):
    """
    Development-level reviewer authentication (§68, §111).

    The key comes from the REVIEW_API_KEY environment variable — never from
    source code (Phase 7 BUG-020). When it is not configured the review API is
    disabled rather than open. This is a shared-secret scheme, not per-user
    authentication; see docs/phase7-limitations.md.
    """
    expected = settings.REVIEW_API_KEY
    if not expected:
        raise HTTPException(status_code=403, detail="Review API is not configured.")
    if not x_review_key or not hmac.compare_digest(x_review_key.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Unauthorized reviewer access.")


# ═══════════════════════════════════════════════════════════════
# REQUEST SCHEMAS (§123)
# ═══════════════════════════════════════════════════════════════

class ResolveRequest(BaseModel):
    """Request body to resolve a review case."""
    action: str = Field(
        ...,
        description="Reviewer action: APPROVE, REJECT, REQUEST_INFORMATION, MARK_UNVERIFIABLE"
    )
    reviewer_id: str = Field(default="admin", description="Reviewer identifier")
    note: str = Field(default="", description="Reviewer note")


class DismissRequest(BaseModel):
    """Request body to dismiss a review case."""
    reviewer_id: str = Field(default="admin")
    note: str = Field(default="")


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS (§122)
# ═══════════════════════════════════════════════════════════════

@router.get("", summary="List all review cases")
async def list_cases(
    status: Optional[str] = None,
    x_review_key: Optional[str] = Header(None),
):
    """GET /review-cases — list review cases with optional status filter."""
    _check_reviewer_auth(x_review_key)

    status_filter = None
    if status:
        try:
            status_filter = ReviewStatus(status.upper())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status: {status}. Valid: {[s.value for s in ReviewStatus]}"
            )

    cases = get_all_cases(status_filter)
    return {
        "cases": [_case_to_dict(c) for c in cases],
        "stats": get_queue_stats(),
    }


@router.get("/{case_id}", summary="Get a single review case")
async def get_single_case(
    case_id: str,
    x_review_key: Optional[str] = Header(None),
):
    """GET /review-cases/{id} — get case details."""
    _check_reviewer_auth(x_review_key)

    case = get_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail=f"Case {case_id} not found.")

    audit = get_audit_log(case_id)
    return {
        "case": _case_to_dict(case),
        "audit_log": [
            {
                "action": e.action,
                "reviewer": e.reviewer,
                "timestamp": e.timestamp,
                "note": e.note,
            }
            for e in audit
        ],
    }


@router.post("/{case_id}/resolve", summary="Resolve a review case")
async def resolve_review_case(
    case_id: str,
    request: ResolveRequest,
    x_review_key: Optional[str] = Header(None),
):
    """POST /review-cases/{id}/resolve — reviewer action (§63)."""
    _check_reviewer_auth(x_review_key)

    # Validate action (§123)
    try:
        action = ReviewAction(request.action.upper())
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid action: {request.action}. Valid: {[a.value for a in ReviewAction]}"
        )

    result = resolve_case(
        case_id=case_id,
        action=action,
        reviewer_id=request.reviewer_id,
        note=request.note,
    )

    if not result:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot resolve case {case_id}. Case not found or invalid status transition."
        )

    return {"case": _case_to_dict(result), "message": f"Case {action.value} successfully."}


@router.post("/{case_id}/dismiss", summary="Dismiss a review case")
async def dismiss_review_case(
    case_id: str,
    request: DismissRequest,
    x_review_key: Optional[str] = Header(None),
):
    """POST /review-cases/{id}/dismiss (§125)."""
    _check_reviewer_auth(x_review_key)

    result = dismiss_case(
        case_id=case_id,
        reviewer_id=request.reviewer_id,
        note=request.note,
    )

    if not result:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot dismiss case {case_id}. Not found or invalid transition."
        )

    return {"case": _case_to_dict(result), "message": "Case dismissed."}


@router.get("/stats/summary", summary="Review queue stats")
async def queue_stats(
    x_review_key: Optional[str] = Header(None),
):
    """Get review queue summary stats."""
    _check_reviewer_auth(x_review_key)
    return get_queue_stats()


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _case_to_dict(case) -> dict:
    """Convert ReviewCase to serializable dict."""
    return {
        "case_id": case.case_id,
        "session_id": case.session_id,
        "created_at": case.created_at,
        "status": case.status.value,
        "reason": case.reason.value,
        "query": case.query,
        "profile_snapshot": case.profile_snapshot,
        "scheme_ids": case.scheme_ids,
        "eligibility_results": case.eligibility_results,
        "source_conflicts": case.source_conflicts,
        "reviewer_id": case.reviewer_id,
        "reviewer_action": case.reviewer_action,
        "reviewer_note": case.reviewer_note,
        "reviewed_at": case.reviewed_at,
    }
