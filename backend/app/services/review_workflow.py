"""
Human-review workflow (docs/HUMAN_REVIEW.md) — the reviewer dashboard's service layer.

    PENDING ──claim / assign / request verification──▶ IN_REVIEW ──approve / reject / mark
       ▲                                                  │  │     unverifiable / resolve──▶ RESOLVED
       └──────────────────── release ─────────────────────┘  │
    PENDING / IN_REVIEW ──dismiss──▶ DISMISSED               └─ request verification (stays IN_REVIEW,
                                                                 "awaiting verification")
RESOLVED and DISMISSED are final. Rules:
  - only the assigned reviewer acts on an IN_REVIEW case (others get 409; an admin can reassign);
  - every change carries the version the reviewer saw (optimistic locking: a stale view gets 409,
    so two reviewers can never both claim or decide the same case);
  - decisions and dismissals need a note; every step is written to the case history and to the
    audit log in the same transaction;
  - a decision is a human verdict stored next to the automated result — it never changes eligibility
    results or scheme rules. A rule that is wrong is corrected through the verified, versioned
    scheme-update process (docs/SCHEME_UPDATES.md); REJECT can flag "data correction needed".

Access policy (docs/HUMAN_REVIEW.md) — checked here on every call, whatever the client shows:
  - only APPROVED reviewer accounts hold review permissions (Principal.for_account), administrators
    oversee (read, assign, grant) but never decide; everyone else gets 403 / 401;
  - a reviewer sees the full case only when it is ASSIGNED to them or they hold an active, expiring
    GRANT for it; otherwise it does not exist for them (404, audited as DENIED). The unassigned pending
    queue is listed as summaries only (no question, profile or evidence) so it can be taken;
  - grantees may read and comment, never decide; only the assignee acts;
  - every case view and queue view is audited; views are rate-limited per reviewer (anti-scraping);
  - the development-only review key sees only cases not linked to a farmer.

Cases live in PostgreSQL; without a database (keyless demo, offline evaluation) the same workflow
runs on the in-memory queue of review_service.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.core.permissions import Permission, Principal, authorize
from app.core.rate_limit import limiter
from app.core.redaction import redact
from app.models.review import DECISIONS, ReviewAction, ReviewReason, ReviewStatus, SENSITIVE_FIELDS
from app.services import review_store

logger = get_logger(__name__)

SYSTEM = "system"
OPEN = (ReviewStatus.PENDING.value, ReviewStatus.IN_REVIEW.value)
MIN_NOTE = 3
MAX_NOTE = 2000

# Profile fields a reviewer may see — and only those the triggering rules actually use.
_PROFILE_FIELDS = {"state", "district", "land_size_acres", "has_land", "primary_crop", "occupation", "age",
                   "gender", "category", "residence", "income_range"}
_RULE_FIELD_TO_PROFILE = {"has_land": "land_size_acres", "land": "land_size_acres", "land_size": "land_size_acres",
                          "crop": "primary_crop", "caste": "category", "social_category": "category"}

# What a farmer is told (never reviewer names or notes).
REASON_TEXT = {
    "UNVERIFIABLE": "We couldn't check your eligibility for this scheme automatically.",
    "RULE_CONFLICT": "This scheme's official rules seem to contradict each other.",
    "SOURCE_CONFLICT": "Official sources gave different information about this scheme.",
    "SYSTEM_ERROR": "Some of our information sources were unavailable when you searched.",
    "INSUFFICIENT_DATA": "We didn't have enough information to give a reliable answer.",
    "AMBIGUOUS_QUERY": "Your question could be read in more than one way.",
    "OTHER": "Your result needs a check by a person.",
}
OUTCOME_TEXT = {
    None: "A person from our team is checking this. Until then, treat this result as unconfirmed and check "
          "the official website before applying.",
    "AWAITING": "Our team is checking this with the official source. Until then, treat this result as "
                "unconfirmed.",
    "APPROVE": "Our team checked this and confirmed the result.",
    "REJECT": "Our team found a problem with this information. It is being corrected — please check the "
              "official website or office before applying.",
    "MARK_UNVERIFIABLE": "Our team couldn't verify this. Please confirm with the official website or office "
                         "before applying.",
    "RESOLVE": "Our team looked into this and the issue has been resolved.",
    "DISMISSED": "Our team checked this; no action was needed.",
}


class ReviewError(Exception):
    def __init__(self, code: str, message: str, status: int):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _store():
    return review_store.get_store()


# ─── escalation (system) ──────────────────────────────────────────────────────

def _sv(x) -> str:
    return getattr(x, "value", x) or ""


def minimal_profile(profile: Dict[str, Any], results: list) -> Dict[str, Any]:
    """Only the profile fields the triggering rules use (plus state); never identity fields."""
    used = {"state"}
    for r in results:
        for rr in getattr(r, "rule_results", None) or []:
            f = str(getattr(rr, "field", "")).lower()
            used.add(_RULE_FIELD_TO_PROFILE.get(f, f))
    return {k: v for k, v in (profile or {}).items()
            if k in used and k in _PROFILE_FIELDS and k not in SENSITIVE_FIELDS and v is not None}


def build_case(session_id: str, query: str, reason: ReviewReason, profile: dict, results: list,
               candidates: list, source_conflicts: list, retrieval_errors: dict) -> Dict[str, Any]:
    urls = {}
    for c in candidates or []:
        sid = c.get("scheme_id") if isinstance(c, dict) else getattr(c, "scheme_id", None)
        url = c.get("official_url") if isinstance(c, dict) else getattr(c, "official_url", None)
        if sid:
            urls[sid] = url
    if reason == ReviewReason.SOURCE_CONFLICT:
        conflict_ids = {c.get("scheme_id") for c in source_conflicts if isinstance(c, dict)}
        results = [r for r in results if getattr(r, "scheme_id", None) in conflict_ids] or results
    schemes, evidence, rule_conflicts, elig = [], [], [], []
    for r in results:
        sid = getattr(r, "scheme_id", "")
        schemes.append({"scheme_id": sid, "name": getattr(r, "scheme_name", "") or sid,
                        "official_url": urls.get(sid)})
        for ref in getattr(r, "source_references", None) or []:
            evidence.append({"scheme_id": sid, "field": ref.get("field"), "text": ref.get("text"),
                             "url": ref.get("url") or urls.get(sid)})
        for c in getattr(r, "conflicts", None) or []:
            rule_conflicts.append({"scheme_id": sid, **c})
        elig.append({"scheme_id": sid, "status": _sv(getattr(r, "status", "")),
                     "missing_information": list(getattr(r, "missing_information", []) or []),
                     "summary": getattr(r, "evidence_summary", None)})
    return {
        "case_id": uuid.uuid4().hex[:12], "session_id": (session_id or "unknown")[:100],
        "reason": reason.value, "status": ReviewStatus.PENDING.value, "query": redact(query or "", 500),
        "profile_snapshot": minimal_profile(profile, results),
        "scheme_ids": [s["scheme_id"] for s in schemes], "schemes": schemes,
        "eligibility_results": elig, "evidence": evidence[:50], "rule_conflicts": rule_conflicts,
        "source_conflicts": [c if isinstance(c, dict) else {"conflict": str(c)} for c in source_conflicts or []],
        "failed_channels": sorted(k for k, v in (retrieval_errors or {}).items() if v),
    }


async def escalate(session_id: str, query: str, profile: dict, results: list, candidates: list,
                   source_conflicts: list, retrieval_errors: dict) -> Optional[Dict[str, Any]]:
    """Open a case on a deterministic trigger (one open case per session and reason)."""
    from app.services.review_service import should_escalate
    reason = should_escalate(results, source_conflicts or [], retrieval_errors or {})
    if reason is None:
        return None
    if reason == ReviewReason.RULE_CONFLICT:
        triggering = [r for r in results if getattr(r, "conflicts", None)]
    elif reason == ReviewReason.UNVERIFIABLE:
        triggering = [r for r in results if _sv(getattr(r, "status", None)) == "UNVERIFIABLE"]
    else:
        triggering = list(results)
    row = build_case(session_id, query, reason, profile, triggering, candidates, source_conflicts, retrieval_errors)
    case, created = await _store().insert(row, f"Auto-escalated: {reason.value}")
    if created:
        logger.info(f"Review case created: {case['case_id']} reason={reason.value}")
    return case


async def link_farmer(case_id: str, farmer_pk: int) -> None:
    """Remember which signed-in farmer the case is about, so they can follow it."""
    await _store().link_farmer(case_id, farmer_pk)


async def link_review_case(case_id: str, farmer_uuid: str) -> None:
    """Chat / voice: link the case to the signed-in account. Never breaks the reply."""
    try:
        from app.services import profile_service
        farmer = await profile_service.profile_repo.get_farmer_by_farmer_id(farmer_uuid)
        if farmer:
            await link_farmer(case_id, farmer.id)
    except Exception as exc:
        logger.warning(f"Review case not linked to the farmer: {type(exc).__name__}")


# ─── access policy ────────────────────────────────────────────────────────────

ADMIN, ASSIGNED, GRANTED, QUEUE, KEY = "admin", "assigned", "granted", "queue", "key"
_HIDDEN = ("NOT_FOUND", "Case not found.", 404)       # out of scope looks exactly like "doesn't exist"


def _is_admin(principal: Principal) -> bool:
    return principal.can(Permission.REVIEW_CASE_ASSIGN)


def _scope(principal: Principal) -> Optional[review_store.Scope]:
    if _is_admin(principal):
        return None
    if principal.via == "review_key":
        return review_store.Scope(unlinked_only=True)
    return review_store.Scope(label=principal.label, pk=principal.account_pk, queue=settings.REVIEW_SELF_ASSIGN)


async def access(principal: Principal, case: Dict[str, Any]) -> Optional[str]:
    """How this principal may see *case*: admin / assigned / granted / key / queue (summary only) / None."""
    if not principal.can(Permission.REVIEW_CASE_READ):
        return None
    if _is_admin(principal):
        return ADMIN
    if principal.via == "review_key":
        if case.get("farmer_pk") is not None:
            return None
        return ASSIGNED if case["assignee"] == principal.label else KEY
    if case["assignee"] == principal.label:
        return ASSIGNED
    if principal.account_pk is not None and await _store().has_grant(case["case_id"], principal.account_pk):
        return GRANTED
    if settings.REVIEW_SELF_ASSIGN and case["status"] == ReviewStatus.PENDING.value and not case["assignee"]:
        return QUEUE
    return None


async def _deny(principal: Principal, case_id: str, what: str) -> ReviewError:
    try:
        await _store().audit(principal, "REVIEW_CASE_ACCESS_DENIED", case_id, {"attempt": what}, outcome="DENIED")
    except Exception as exc:
        logger.error(f"Denied review access not audited: {type(exc).__name__}")
    return ReviewError(*_HIDDEN)


async def _case_for(principal: Principal, case_id: str, allowed: tuple, what: str) -> tuple:
    """The case and the caller's access level, if it is one of *allowed*; else 404 (audited)."""
    case = await _store().get(case_id)
    level = await access(principal, case) if case else None
    if case is None or level not in allowed:
        raise await _deny(principal, case_id, what)
    return case, level


def summary(case: Dict[str, Any], level: Optional[str]) -> Dict[str, Any]:
    """Queue listing: enough to pick a case, nothing about the farmer or the evidence."""
    return {
        "case_id": case["case_id"], "reason": case["reason"], "status": case["status"],
        "schemes": [{"scheme_id": x["scheme_id"], "name": x.get("name") or x["scheme_id"]}
                    for x in case.get("schemes") or []],
        "assignee": case["assignee"], "awaiting_verification": case["awaiting_verification"],
        "decision": case["decision"], "version": case["version"],
        "created_at": case["created_at"], "updated_at": case["updated_at"], "access": level,
    }


# ─── reviewer reads ───────────────────────────────────────────────────────────

async def list_cases(principal: Principal, status: Optional[str] = None, reason: Optional[str] = None,
                     assigned: Optional[str] = None, limit: int = 20, offset: int = 0) -> Dict[str, Any]:
    """The cases in the caller's scope, as summaries."""
    authorize(principal, Permission.REVIEW_CASE_READ)
    assignee = principal.label if assigned == "me" else ("" if assigned == "unassigned" else None)
    scope = _scope(principal)
    rows, total = await _store().list(status, reason, assignee, limit, offset, scope)
    items = [summary(r, await access(principal, r)) for r in rows]
    await _store().audit(principal, "REVIEW_QUEUE_VIEWED", None,
                         {"status": status, "reason": reason, "assigned": assigned, "returned": len(items)})
    return {"cases": items, "total": total, "stats": await _store().stats(scope)}


async def get_case(principal: Principal, case_id: str) -> Dict[str, Any]:
    """The full case (minimal profile, evidence, history) — assigned / granted / admin only. Audited."""
    authorize(principal, Permission.REVIEW_CASE_READ)
    if limiter.hit("review_case_view", principal.label, settings.REVIEW_VIEWS_PER_10_MIN, 600) is not None:
        try:
            await _store().audit(principal, "REVIEW_CASE_VIEWED", case_id, {"refused": "RATE_LIMITED"},
                                 outcome="DENIED")
        except Exception:
            pass
        raise ReviewError("RATE_LIMITED", "Too many case views in a short time. Please wait a few minutes.", 429)
    case, level = await _case_for(principal, case_id, (ADMIN, ASSIGNED, GRANTED, KEY), "view")
    await _store().audit(principal, "REVIEW_CASE_VIEWED", case_id, {"access": level})
    out = {"case": case, "history": await _store().events(case_id), "access": level}
    if level == ADMIN:
        out["grants"] = await _store().grants(case_id)
    return out


async def stats(principal: Principal) -> Dict[str, int]:
    authorize(principal, Permission.REVIEW_CASE_READ)
    return await _store().stats(_scope(principal))


# ─── transitions ──────────────────────────────────────────────────────────────

def _note(note: Optional[str], required: bool) -> str:
    text = (note or "").strip()
    if required and len(text) < MIN_NOTE:
        raise ReviewError("NOTE_REQUIRED", "Write a note explaining the decision (what you checked).", 422)
    return redact(text, MAX_NOTE) if text else ""


def _check_version(case: Dict[str, Any], expected_version: Optional[int]) -> None:
    if expected_version is not None and expected_version != case["version"]:
        raise ReviewError("VERSION_CONFLICT", "This case was changed by someone else. Reload it and try again.", 409)


def _invalid(case, what: str) -> ReviewError:
    return ReviewError("INVALID_TRANSITION", f"A {case['status'].lower().replace('_', ' ')} case can't be {what}.", 409)


async def _apply(principal: Principal, case: Dict[str, Any], changes: Dict[str, Any], event: str,
                 note: str, audit_action: str) -> Dict[str, Any]:
    now = _now()
    changes = {**changes, "reviewer_id": principal.label, "reviewer_action": event, "reviewer_note": note or None,
               "reviewed_at": now}
    updated = await _store().apply(
        case["case_id"], case["version"], changes,
        {"event": event, "actor": principal.label, "from_status": case["status"],
         "to_status": changes.get("status", case["status"]), "note": note or None},
        principal, audit_action,
        {"from": case["status"], "to": changes.get("status", case["status"]), "reason": case["reason"],
         **({"decision": changes["decision"]} if changes.get("decision") else {}),
         **({"assignee": changes["assignee"]} if "assignee" in changes else {})})
    if updated is None:                     # someone else changed it between our read and write
        raise ReviewError("VERSION_CONFLICT", "This case was changed by someone else. Reload it and try again.", 409)
    return updated


async def claim(principal: Principal, case_id: str, expected_version: Optional[int] = None) -> Dict[str, Any]:
    """Take an unassigned pending case: PENDING → IN_REVIEW, assigned to you."""
    authorize(principal, Permission.REVIEW_CASE_DECIDE)
    case, level = await _case_for(principal, case_id, (QUEUE, KEY, ASSIGNED, GRANTED), "claim")
    _check_version(case, expected_version)
    if case["status"] != ReviewStatus.PENDING.value or case["assignee"]:
        if case["status"] == ReviewStatus.IN_REVIEW.value and case["assignee"] != principal.label:
            raise ReviewError("ASSIGNED_TO_OTHER", "This case is already assigned to another reviewer.", 409)
        raise _invalid(case, "claimed")
    return await _apply(principal, case, {"status": ReviewStatus.IN_REVIEW.value, "assignee": principal.label,
                                          "assigned_at": _now()}, "ASSIGNED", "", "REVIEW_ASSIGNED")


async def release(principal: Principal, case_id: str, expected_version: Optional[int] = None) -> Dict[str, Any]:
    """Give a case back to the queue: IN_REVIEW → PENDING (assignee only)."""
    authorize(principal, Permission.REVIEW_CASE_DECIDE)
    case, level = await _case_for(principal, case_id, (ASSIGNED, GRANTED, KEY), "release")
    _check_version(case, expected_version)
    if case["status"] != ReviewStatus.IN_REVIEW.value:
        raise _invalid(case, "released")
    if level != ASSIGNED:
        raise ReviewError("ASSIGNED_TO_OTHER", "Only the assigned reviewer can release this case.", 409)
    return await _apply(principal, case, {"status": ReviewStatus.PENDING.value, "assignee": None,
                                          "assigned_at": None, "awaiting_verification": False},
                        "UNASSIGNED", "", "REVIEW_UNASSIGNED")


async def _approved_reviewer(email: str):
    from app.services import auth_service
    target = await auth_service.repo.get_farmer_by_email((email or "").strip().lower())
    if (target is None or not target.is_active or getattr(target, "role", None) != "REVIEWER"
            or not getattr(target, "reviewer_approved_at", None)):
        raise ReviewError("NOT_A_REVIEWER", "Choose an active, approved reviewer account.", 422)
    return target


async def assign(principal: Principal, case_id: str, reviewer_email: str,
                 expected_version: Optional[int] = None) -> Dict[str, Any]:
    """Administrators assign or reassign an open case to an active, APPROVED reviewer."""
    authorize(principal, Permission.REVIEW_CASE_ASSIGN)
    target = await _approved_reviewer(reviewer_email)
    case, _ = await _case_for(principal, case_id, (ADMIN,), "assign")
    _check_version(case, expected_version)
    if case["status"] not in OPEN:
        raise _invalid(case, "assigned")
    if case["assignee"] == target.email:
        return case
    return await _apply(principal, case, {"status": ReviewStatus.IN_REVIEW.value, "assignee": target.email,
                                          "assigned_at": _now()},
                        "ASSIGNED", f"Assigned to {target.email}", "REVIEW_ASSIGNED")


async def grant_access(principal: Principal, case_id: str, reviewer_email: str, hours: int) -> Dict[str, Any]:
    """Administrators let one more approved reviewer read (and comment on) a case, for a limited time."""
    authorize(principal, Permission.REVIEW_CASE_ASSIGN)
    if not 1 <= hours <= settings.REVIEW_GRANT_MAX_HOURS:
        raise ReviewError("BAD_DURATION", f"Grant between 1 and {settings.REVIEW_GRANT_MAX_HOURS} hours.", 422)
    target = await _approved_reviewer(reviewer_email)
    case, _ = await _case_for(principal, case_id, (ADMIN,), "grant")
    if case["assignee"] == target.email:
        raise ReviewError("ALREADY_ASSIGNED", "That reviewer is assigned to the case already.", 409)
    g = await _store().grant(case_id, target.id, principal.label, _now() + timedelta(hours=hours), principal,
                             {"reviewer": target.email, "hours": hours})
    return {"reviewer": target.email, "expires_at": g["expires_at"]}


async def revoke_access(principal: Principal, case_id: str, reviewer_email: str) -> None:
    authorize(principal, Permission.REVIEW_CASE_ASSIGN)
    from app.services import auth_service
    target = await auth_service.repo.get_farmer_by_email((reviewer_email or "").strip().lower())
    await _case_for(principal, case_id, (ADMIN,), "revoke grant")
    if target is None or not await _store().revoke_grant(case_id, target.id, principal.label, principal,
                                                         {"reviewer": target.email}):
        raise ReviewError("NO_GRANT", "That reviewer has no active grant on this case.", 404)


async def comment(principal: Principal, case_id: str, text: str) -> Dict[str, Any]:
    """Add a reviewer comment (assignee or grantee; comments never change the case)."""
    authorize(principal, Permission.REVIEW_CASE_DECIDE)
    note = _note(text, required=True)
    case, _ = await _case_for(principal, case_id, (ASSIGNED, GRANTED, KEY), "comment")
    return await _store().add_event(case_id, {"event": "COMMENT", "actor": principal.label,
                                              "from_status": case["status"], "to_status": case["status"],
                                              "note": note}, principal, "REVIEW_COMMENTED")


async def act(principal: Principal, case_id: str, action: ReviewAction, note: Optional[str] = None,
              expected_version: Optional[int] = None, data_correction_needed: bool = False) -> Dict[str, Any]:
    """
    REQUEST_INFORMATION ("request additional verification"): a pending case is taken (→ IN_REVIEW) and
    marked awaiting verification. APPROVE / REJECT / MARK_UNVERIFIABLE / RESOLVE: IN_REVIEW → RESOLVED.
    Only the assignee (a grantee may read and comment, never decide).
    """
    authorize(principal, Permission.REVIEW_CASE_DECIDE)
    if action == ReviewAction.REQUEST_INFORMATION:
        text = _note(note, required=False)
        case, level = await _case_for(principal, case_id, (ASSIGNED, QUEUE, KEY, GRANTED), "request verification")
        _check_version(case, expected_version)
        if case["status"] not in OPEN:
            raise _invalid(case, "sent for verification")
        if case["assignee"] and level != ASSIGNED:
            raise ReviewError("ASSIGNED_TO_OTHER", "Only the assigned reviewer can act on this case.", 409)
        changes: Dict[str, Any] = {"status": ReviewStatus.IN_REVIEW.value, "awaiting_verification": True}
        if not case["assignee"]:
            changes.update(assignee=principal.label, assigned_at=_now())
        return await _apply(principal, case, changes, "VERIFICATION_REQUESTED", text, "REVIEW_REQUEST_INFORMATION")
    if action not in DECISIONS:
        raise ReviewError("BAD_ACTION", "Unknown action.", 422)
    text = _note(note, required=True)
    case, level = await _case_for(principal, case_id, (ASSIGNED, QUEUE, KEY, GRANTED), "decide")
    _check_version(case, expected_version)
    if case["status"] != ReviewStatus.IN_REVIEW.value:
        raise ReviewError("INVALID_TRANSITION", "Take the case first (claim it or request verification): only a "
                          "case in review can be decided." if case["status"] == "PENDING" else
                          f"A {case['status'].lower()} case can't be decided again.", 409)
    if level != ASSIGNED:
        raise ReviewError("ASSIGNED_TO_OTHER", "Only the assigned reviewer can decide this case.", 409)
    return await _apply(principal, case, {
        "status": ReviewStatus.RESOLVED.value, "decision": action.value, "awaiting_verification": False,
        "data_correction_needed": bool(data_correction_needed and action == ReviewAction.REJECT)},
        action.value, text, f"REVIEW_{action.value}")


async def dismiss(principal: Principal, case_id: str, note: Optional[str] = None,
                  expected_version: Optional[int] = None) -> Dict[str, Any]:
    """PENDING / IN_REVIEW → DISMISSED (e.g. a duplicate or a false alarm). Needs a note."""
    authorize(principal, Permission.REVIEW_CASE_DECIDE)
    text = _note(note, required=True)
    case, level = await _case_for(principal, case_id, (ASSIGNED, QUEUE, KEY, GRANTED), "dismiss")
    _check_version(case, expected_version)
    if case["status"] not in OPEN:
        raise _invalid(case, "dismissed")
    if case["assignee"] and level != ASSIGNED:
        raise ReviewError("ASSIGNED_TO_OTHER", "Only the assigned reviewer can dismiss this case.", 409)
    changes: Dict[str, Any] = {"status": ReviewStatus.DISMISSED.value, "awaiting_verification": False}
    if not case["assignee"]:            # dismissed straight from the queue: it becomes the dismisser's case
        changes.update(assignee=principal.label, assigned_at=_now())
    return await _apply(principal, case, changes, "DISMISSED", text, "REVIEW_DISMISSED")


# ─── what the farmer sees ─────────────────────────────────────────────────────

def farmer_view(case: Dict[str, Any]) -> Dict[str, Any]:
    """A farmer's own case: plain-language reason and outcome; no reviewer, notes or evidence."""
    status = case["status"]
    key = (case["decision"] if status == ReviewStatus.RESOLVED.value
           else "DISMISSED" if status == ReviewStatus.DISMISSED.value
           else "AWAITING" if case.get("awaiting_verification") else None)
    return {
        "case_id": case["case_id"],
        "schemes": [{"scheme_id": s["scheme_id"], "name": s.get("name") or s["scheme_id"]}
                    for s in case.get("schemes") or []] or [{"scheme_id": s, "name": s} for s in case["scheme_ids"]],
        "reason": case["reason"], "reason_text": REASON_TEXT.get(case["reason"], REASON_TEXT["OTHER"]),
        "status": status, "open": status in OPEN, "outcome_text": OUTCOME_TEXT[key],
        "opened_at": case["created_at"], "updated_at": case["updated_at"],
    }


async def cases_for_farmer(farmer_pk: int) -> List[Dict[str, Any]]:
    return [farmer_view(c) for c in await _store().for_farmer(farmer_pk)]


async def open_scheme_ids_for_farmer(farmer_pk: int) -> set:
    return {sid for c in await _store().for_farmer(farmer_pk) if c["status"] in OPEN for sid in c["scheme_ids"]}
