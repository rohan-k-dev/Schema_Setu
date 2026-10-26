"""
Where review cases live (docs/HUMAN_REVIEW.md): PostgreSQL when the database is connected,
otherwise the in-memory queue of review_service (keyless demo, offline evaluation).

Both stores offer the same operations and the same guarantees the workflow relies on:
one open case per (session, reason); changes are compare-and-swap on the case version;
every change writes a history event (and an audit event); listings can be limited to a
reviewer's scope (assigned, granted, or the unassigned pending queue).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging import get_logger
from app.core.permissions import Principal
from app.models.review import ReviewAuditEntry, ReviewCase, ReviewReason, ReviewStatus

logger = get_logger(__name__)

_OPEN = (ReviewStatus.PENDING, ReviewStatus.IN_REVIEW)


@dataclass(frozen=True)
class Scope:
    """Which cases a caller may list. None (no scope) = all cases (administrators)."""
    label: Optional[str] = None          # assignee label (e-mail / "review-key")
    pk: Optional[int] = None             # account id, for grants
    queue: bool = False                  # also the unassigned PENDING queue (self-assignment)
    unlinked_only: bool = False          # only cases not linked to a farmer (development review key)


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PgStore:
    """PostgreSQL (app.database.repositories.review_repository)."""

    durable_audit = True

    @staticmethod
    def _repo():
        from app.database.repositories import review_repository
        return review_repository

    async def insert(self, row, note):
        return await self._repo().insert(row, SYSTEM_PRINCIPAL, note)

    async def get(self, case_id):
        return await self._repo().get(case_id)

    async def list(self, status, reason, assignee, limit, offset, scope=None):
        return await self._repo().list_cases(status, reason, assignee, limit, offset, scope)

    async def stats(self, scope=None):
        return await self._repo().stats(scope)

    async def apply(self, case_id, version, changes, event, actor, audit_action, audit_details):
        return await self._repo().apply(case_id, version, changes, event, actor, audit_action, audit_details)

    async def add_event(self, case_id, event, actor, audit_action):
        return await self._repo().add_event(case_id, event, actor, audit_action)

    async def events(self, case_id):
        return await self._repo().events(case_id)

    async def link_farmer(self, case_id, farmer_pk):
        await self._repo().link_farmer(case_id, farmer_pk)

    async def for_farmer(self, farmer_pk):
        return await self._repo().for_farmer(farmer_pk)

    async def has_grant(self, case_id, reviewer_pk):
        return await self._repo().has_grant(case_id, reviewer_pk)

    async def grant(self, case_id, reviewer_pk, by, expires_at, actor, details):
        return await self._repo().grant(case_id, reviewer_pk, by, expires_at, actor, details)

    async def revoke_grant(self, case_id, reviewer_pk, by, actor, details):
        return await self._repo().revoke_grant(case_id, reviewer_pk, by, actor, details)

    async def grants(self, case_id):
        return await self._repo().grants(case_id)

    async def audit(self, actor, action, case_id, details, outcome="SUCCESS"):
        # durable store: an access that can't be recorded is refused (fail closed)
        from app.database.repositories import audit_repository
        await audit_repository.record(actor, action, "review_case", case_id, details, outcome=outcome)


class MemoryStore:
    """The in-memory queue (review_service._review_cases / _audit_log / _review_grants), read at call time."""

    durable_audit = False

    @staticmethod
    def _svc():
        from app.services import review_service
        return review_service

    @staticmethod
    def to_dict(c: ReviewCase) -> Dict[str, Any]:
        d = asdict(c)
        d["status"] = c.status.value
        d["reason"] = c.reason.value
        d["updated_at"] = c.updated_at or c.created_at
        d.pop("created_by_system", None)
        return d

    def _grant_rows(self, case_id) -> Dict[int, dict]:
        return self._svc()._review_grants.setdefault(case_id, {})

    def _active(self, case_id, pk) -> bool:
        g = self._svc()._review_grants.get(case_id, {}).get(pk)
        return bool(g and not g["revoked_at"] and g["expires_at"] > _now())

    def _in_scope(self, r: Dict[str, Any], scope: Optional[Scope]) -> bool:
        if scope is None:
            return True
        if scope.unlinked_only and r.get("farmer_pk") is not None:
            return False
        if scope.label is None:                      # key: every unlinked case
            return True
        return (r["assignee"] == scope.label or (scope.pk is not None and self._active(r["case_id"], scope.pk))
                or (scope.queue and r["status"] == "PENDING" and not r["assignee"]))

    async def insert(self, row, note):
        svc = self._svc()
        for c in svc._review_cases.values():
            if c.session_id == row["session_id"] and c.reason.value == row["reason"] and c.status in _OPEN:
                return self.to_dict(c), False
        case = ReviewCase(**{**row, "status": ReviewStatus(row["status"]), "reason": ReviewReason(row["reason"])})
        case.updated_at = case.created_at
        svc._review_cases[case.case_id] = case
        svc._audit_log.append(ReviewAuditEntry(case_id=case.case_id, action="CREATED", note=note,
                                               to_status="PENDING"))
        await self.audit(SYSTEM_PRINCIPAL, "REVIEW_CASE_CREATED", case.case_id, {"reason": row["reason"]})
        return self.to_dict(case), True

    async def get(self, case_id):
        c = self._svc()._review_cases.get(case_id)
        return self.to_dict(c) if c else None

    async def list(self, status, reason, assignee, limit, offset, scope=None):
        rows = [self.to_dict(c) for c in self._svc()._review_cases.values()]
        rows = [r for r in rows if (not status or r["status"] == status) and (not reason or r["reason"] == reason)
                and (assignee is None or (r["assignee"] or "") == assignee) and self._in_scope(r, scope)]
        oldest_first = status in ("PENDING", "IN_REVIEW")
        rows.sort(key=lambda r: (r["created_at"], r["case_id"]), reverse=not oldest_first)
        return rows[offset:offset + limit], len(rows)

    async def stats(self, scope=None):
        rows = [r for r in (self.to_dict(c) for c in self._svc()._review_cases.values()) if self._in_scope(r, scope)]
        out = {"total": len(rows)}
        for s in ReviewStatus:
            out[s.value.lower()] = sum(1 for r in rows if r["status"] == s.value)
        out["awaiting_verification"] = sum(1 for r in rows if r["awaiting_verification"])
        return out

    async def apply(self, case_id, version, changes, event, actor, audit_action, audit_details):
        svc = self._svc()
        c = svc._review_cases.get(case_id)
        if c is None or c.version != version:          # no await between check and write: atomic
            return None
        for k, v in changes.items():
            if k == "status":
                v = ReviewStatus(v)
            setattr(c, k, _iso(v))
        c.version += 1
        c.updated_at = _now().isoformat()
        svc._audit_log.append(_entry(case_id, event))
        await self.audit(actor, audit_action, case_id, audit_details)
        return self.to_dict(c)

    async def add_event(self, case_id, event, actor, audit_action):
        svc = self._svc()
        c = svc._review_cases[case_id]
        c.updated_at = _now().isoformat()
        entry = _entry(case_id, event)
        svc._audit_log.append(entry)
        await self.audit(actor, audit_action, case_id, {})
        return _event_dict(entry)

    async def events(self, case_id):
        return [_event_dict(e) for e in self._svc().get_audit_log(case_id)]

    async def link_farmer(self, case_id, farmer_pk):
        c = self._svc()._review_cases.get(case_id)
        if c and c.farmer_pk is None:
            c.farmer_pk = farmer_pk

    async def for_farmer(self, farmer_pk):
        rows = [self.to_dict(c) for c in self._svc()._review_cases.values() if c.farmer_pk == farmer_pk]
        return sorted(rows, key=lambda r: r["created_at"], reverse=True)

    async def has_grant(self, case_id, reviewer_pk):
        return self._active(case_id, reviewer_pk)

    async def grant(self, case_id, reviewer_pk, by, expires_at, actor, details):
        self._grant_rows(case_id)[reviewer_pk] = {"reviewer_pk": reviewer_pk, "granted_by": by,
                                                  "granted_at": _now(), "expires_at": expires_at,
                                                  "revoked_at": None, "revoked_by": None}
        await self.audit(actor, "REVIEW_ACCESS_GRANTED", case_id, details)
        return dict(self._grant_rows(case_id)[reviewer_pk])

    async def revoke_grant(self, case_id, reviewer_pk, by, actor, details):
        g = self._grant_rows(case_id).get(reviewer_pk)
        if not g or g["revoked_at"]:
            return False
        g.update(revoked_at=_now(), revoked_by=by)
        await self.audit(actor, "REVIEW_ACCESS_REVOKED", case_id, details)
        return True

    async def grants(self, case_id):
        return [dict(g) for g in self._grant_rows(case_id).values()]

    async def audit(self, actor, action, case_id, details, outcome="SUCCESS"):
        # Without a database the in-memory history is the record; audit_events is best effort.
        try:
            from app.database.repositories import audit_repository
            await audit_repository.record(actor, action, "review_case", case_id, details, outcome=outcome)
        except Exception as exc:
            logger.warning(f"Review event not written to audit_events: {type(exc).__name__}")


def _entry(case_id: str, e: Dict[str, Any]) -> ReviewAuditEntry:
    return ReviewAuditEntry(case_id=case_id, action=e["event"], reviewer=e["actor"], note=e.get("note") or "",
                            from_status=e.get("from_status"), to_status=e.get("to_status"))


def _event_dict(e: ReviewAuditEntry) -> Dict[str, Any]:
    return {"event": e.action, "actor": e.reviewer, "from_status": e.from_status, "to_status": e.to_status,
            "note": e.note or None, "created_at": e.timestamp}


SYSTEM_PRINCIPAL = Principal(role=None, label="system", via="system")
_pg, _memory = PgStore(), MemoryStore()


def get_store():
    from app.database import connection
    return _pg if connection.is_db_available() else _memory
