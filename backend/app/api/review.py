"""
Human Review API — Phase 6 (§122–§126), role-based (docs/RBAC.md), reviewer dashboard
workflow (docs/HUMAN_REVIEW.md).

Who may call it (checked on the server, in the dependency and in the service):
  - REVIEWER accounts: read cases, claim / release them, comment, request verification, decide, dismiss;
  - ADMIN accounts: read (oversight) and assign / reassign cases — decisions need a reviewer;
  - FARMER accounts and anonymous callers: nothing (403 / 401); a farmer sees the plain-language
    status of their own cases at GET /farmers/me/review-cases;
  - the development-only shared key (X-Review-Key, REVIEW_API_KEY): read and decide, acting for
    no account; refused when unset or in production (§68, BUG-020).

Access policy (docs/HUMAN_REVIEW.md, enforced in app.services.review_workflow on every call):
only APPROVED reviewer accounts; full cases only when assigned or explicitly granted (otherwise
404, audited); the queue is summaries only; views are audited and rate-limited; responses are
never cached (Cache-Control: no-store); final decisions, dismissals, assignments and grants need
a recent sign-in or password confirmation (403 REAUTH_REQUIRED → POST /auth/reauthenticate).

Every change takes the case version the reviewer saw (``expected_version``; 409 if it moved on).
The reviewer recorded is the authenticated principal; a reviewer name in the body is rejected.

IMPORTANT: Reviewers must NOT directly edit schemes or eligibility_rules from here (§64): a wrong
rule is corrected through the verified, versioned scheme-update process (docs/SCHEME_UPDATES.md).
"""

from datetime import datetime
from typing import Annotated, Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, Field

from app.api.deps import ensure_recent_auth, require
from app.core.logging import get_logger
from app.core.permissions import Permission, Principal
from app.models.review import ReviewAction, ReviewReason, ReviewStatus
from app.services import review_workflow as wf

logger = get_logger(__name__)

async def _no_store(response: Response) -> None:
    """Case data must not be kept by browsers or proxies (no export through caches)."""
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"


router = APIRouter(prefix="/review-cases", tags=["Human Review"], dependencies=[Depends(_no_store)])

can_read = require(Permission.REVIEW_CASE_READ, allow_review_key=True)
can_decide = require(Permission.REVIEW_CASE_DECIDE, allow_review_key=True)
can_assign = require(Permission.REVIEW_CASE_ASSIGN)

CaseId = Annotated[str, Path(pattern=r"^[A-Za-z0-9-]{1,36}$")]
Version = Optional[int]


# ─── request bodies (strict: unknown fields such as reviewer_id give 422) ─────

class _Body(BaseModel):
    model_config = {"extra": "forbid"}


class ResolveRequest(_Body):
    action: str = Field(..., description="APPROVE, REJECT, MARK_UNVERIFIABLE, RESOLVE, or REQUEST_INFORMATION "
                                         "(request additional verification)")
    note: str = Field(default="", max_length=2000, description="Required for decisions")
    expected_version: Version = Field(default=None, ge=1)
    data_correction_needed: bool = Field(default=False, description="REJECT only: the scheme data needs a "
                                         "correction through the scheme-update process")


class DismissRequest(_Body):
    note: str = Field(default="", max_length=2000)
    expected_version: Version = Field(default=None, ge=1)


class VersionRequest(_Body):
    expected_version: Version = Field(default=None, ge=1)


class AssignRequest(_Body):
    reviewer_email: str = Field(..., min_length=3, max_length=254)
    expected_version: Version = Field(default=None, ge=1)


class GrantRequest(_Body):
    reviewer_email: str = Field(..., min_length=3, max_length=254)
    hours: int = Field(default=72, ge=1, le=720)


class RevokeGrantRequest(_Body):
    reviewer_email: str = Field(..., min_length=3, max_length=254)


class CommentRequest(_Body):
    text: str = Field(..., min_length=1, max_length=2000)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


_INTERNAL = ("farmer_pk", "session_id")      # never shown: who the farmer is / their chat thread


def _case(c: Dict[str, Any]) -> Dict[str, Any]:
    """A case for reviewers: evidence and the minimal profile, never the farmer's account."""
    out = {k: _iso(v) for k, v in c.items() if k not in _INTERNAL}
    out["farmer_follows_case"] = c.get("farmer_pk") is not None
    return out


def _summary(c: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _iso(v) for k, v in c.items()}


async def _grant_view(g: Dict[str, Any]) -> Dict[str, Any]:
    from app.services import auth_service
    who = await auth_service.repo.get_farmer_by_pk(g["reviewer_pk"])
    return {"reviewer": who.email if who else None, "granted_by": g["granted_by"], "granted_at": _iso(g["granted_at"]),
            "expires_at": _iso(g["expires_at"]), "revoked_at": _iso(g.get("revoked_at"))}


def _event(e: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _iso(v) for k, v in e.items() if k not in ("id", "case_id")}


async def _run(coro):
    try:
        return await coro
    except wf.ReviewError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})


# ─── reads ────────────────────────────────────────────────────────────────────

@router.get("", summary="Review queue (filters: status, reason, assignment)")
async def list_cases(
    status: Optional[str] = None,
    reason: Optional[str] = None,
    assigned: Optional[Literal["me", "unassigned"]] = None,
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=100_000),
    principal: Principal = Depends(can_read),
):
    """
    Summaries of the cases in your scope: assigned to you, granted to you, and the unassigned
    pending queue (administrators: all). Open cases oldest first; others newest first.
    """
    try:
        status_value = ReviewStatus(status.upper()).value if status else None
        reason_value = ReviewReason(reason.upper()).value if reason else None
    except ValueError:
        raise HTTPException(status_code=400, detail={
            "code": "BAD_FILTER", "message": f"Valid statuses: {[s.value for s in ReviewStatus]}; "
                                             f"reasons: {[r.value for r in ReviewReason]}."})
    out = await _run(wf.list_cases(principal, status_value, reason_value, assigned, limit, offset))
    return {"cases": [_summary(c) for c in out["cases"]], "total": out["total"], "stats": out["stats"]}


@router.get("/stats/summary", summary="Counts per status")
async def queue_stats(principal: Principal = Depends(can_read)):
    return await _run(wf.stats(principal))


@router.get("/{case_id}", summary="One case with its history")
async def get_single_case(case_id: CaseId, principal: Principal = Depends(can_read)):
    out = await _run(wf.get_case(principal, case_id))
    history = [_event(e) for e in out["history"]]
    return {
        "case": _case(out["case"]),
        "access": out["access"],
        **({"grants": [await _grant_view(g) for g in out["grants"]]} if "grants" in out else {}),
        "history": history,
        # earlier shape (phase 6), kept for existing clients
        "audit_log": [{"action": e["event"], "reviewer": e["actor"], "timestamp": e["created_at"],
                       "note": e["note"] or ""} for e in history],
    }


# ─── workflow ─────────────────────────────────────────────────────────────────

@router.post("/{case_id}/claim", summary="Take a pending case (assign it to yourself)")
async def claim(case_id: CaseId, req: VersionRequest = VersionRequest(), principal: Principal = Depends(can_decide)):
    return {"case": _case(await _run(wf.claim(principal, case_id, req.expected_version)))}


@router.post("/{case_id}/release", summary="Give a case back to the queue")
async def release(case_id: CaseId, req: VersionRequest = VersionRequest(), principal: Principal = Depends(can_decide)):
    return {"case": _case(await _run(wf.release(principal, case_id, req.expected_version)))}


@router.post("/{case_id}/assign", summary="Assign or reassign a case to an approved reviewer (administrators)")
async def assign(case_id: CaseId, req: AssignRequest, request: Request, principal: Principal = Depends(can_assign)):
    ensure_recent_auth(request, principal)
    return {"case": _case(await _run(wf.assign(principal, case_id, req.reviewer_email, req.expected_version)))}


@router.post("/{case_id}/grants", status_code=201,
             summary="Let another approved reviewer read and comment on a case, for a limited time (administrators)")
async def grant(case_id: CaseId, req: GrantRequest, request: Request, principal: Principal = Depends(can_assign)):
    ensure_recent_auth(request, principal)
    out = await _run(wf.grant_access(principal, case_id, req.reviewer_email, req.hours))
    return {"grant": {"reviewer": out["reviewer"], "expires_at": _iso(out["expires_at"])}}


@router.post("/{case_id}/grants/revoke", status_code=204, summary="End a reviewer's grant (administrators)")
async def revoke_grant(case_id: CaseId, req: RevokeGrantRequest, principal: Principal = Depends(can_assign)):
    await _run(wf.revoke_access(principal, case_id, req.reviewer_email))


@router.post("/{case_id}/comments", status_code=201, summary="Add a reviewer comment")
async def add_comment(case_id: CaseId, req: CommentRequest, principal: Principal = Depends(can_decide)):
    return {"comment": _event(await _run(wf.comment(principal, case_id, req.text)))}


@router.post("/{case_id}/resolve", summary="Approve, reject, mark unverifiable, resolve, or request verification")
async def resolve_review_case(case_id: CaseId, request: ResolveRequest, http: Request,
                              principal: Principal = Depends(can_decide)):
    try:
        action = ReviewAction(request.action.upper())
    except ValueError:
        raise HTTPException(status_code=400, detail={
            "code": "BAD_ACTION", "message": f"Valid actions: {[a.value for a in ReviewAction]}."})
    if action != ReviewAction.REQUEST_INFORMATION:          # final decisions: recent sign-in required
        ensure_recent_auth(http, principal)
    case = await _run(wf.act(principal, case_id, action, request.note, request.expected_version,
                             request.data_correction_needed))
    return {"case": _case(case), "message": f"Case {action.value} recorded."}


@router.post("/{case_id}/dismiss", summary="Dismiss a case (no action needed)")
async def dismiss_review_case(case_id: CaseId, request: DismissRequest, http: Request,
                              principal: Principal = Depends(can_decide)):
    ensure_recent_auth(http, principal)
    case = await _run(wf.dismiss(principal, case_id, request.note, request.expected_version))
    return {"case": _case(case), "message": "Case dismissed."}
