"""
Administration: accounts (role / status), scheme curation flags and the audit log
(docs/RBAC.md).

Every function takes the server-established Principal and authorizes it here as
well as in the route dependency (defence in depth: a future caller that forgets
the dependency still can't skip the check). Rules enforced in the repository
transaction: no change to your own role or status, never remove the last active
administrator, every change audited.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.core.logging import get_logger
from app.core.permissions import Permission, Principal, authorize
from app.database.repositories import admin_repository as repo
from app.database.repositories import audit_repository as audit_repo
from app.database.repositories.admin_repository import AdminRejected
from app.models.db.farmer_auth import FarmerRow
from app.models.rbac_schemas import (
    AdminUser,
    AdminUserPage,
    AuditEvent,
    AuditIntegrity,
    AuditPage,
    RoleChangeRequest,
    SchemeCuration,
    SchemeCurationRequest,
)

logger = get_logger(__name__)

__all__ = ["AdminRejected", "list_users", "get_user", "change_role", "change_status", "curate_scheme",
           "list_audit_events"]


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


def _user(f: FarmerRow) -> AdminUser:
    return AdminUser(
        farmer_id=f.farmer_id, email=f.email, full_name=f.full_name, role=f.role, is_active=f.is_active,
        is_verified=f.is_verified, locked=bool(f.locked_until and f.locked_until > datetime.now(timezone.utc)),
        reviewer_approved=bool(getattr(f, "reviewer_approved_at", None)),
        created_at=_iso(f.created_at), last_login_at=_iso(f.last_login_at),
    )


async def list_users(principal: Principal, limit: int, offset: int, role: Optional[str] = None,
                     query: Optional[str] = None) -> AdminUserPage:
    authorize(principal, Permission.USER_READ)
    rows, total = await repo.list_accounts(limit, offset, role, query)
    return AdminUserPage(items=[_user(r) for r in rows], total=total, limit=limit, offset=offset)


async def get_user(principal: Principal, farmer_id: str) -> AdminUser:
    authorize(principal, Permission.USER_READ)
    row = await repo.get_account(farmer_id)
    if row is None:
        raise AdminRejected("NOT_FOUND", "Account not found.")
    return _user(row)


async def _audit_failure(principal: Principal, action: str, target_type: str, target_id: str,
                         exc: AdminRejected, details: Optional[dict] = None) -> None:
    """A refused sensitive action is audited too (outcome FAILURE); never masks the refusal."""
    try:
        await audit_repo.record(principal, action, target_type, target_id,
                                {**(details or {}), "refused": exc.code}, outcome="FAILURE")
    except Exception as e:
        logger.warning(f"Could not audit refused {action}: {type(e).__name__}")


async def change_role(principal: Principal, farmer_id: str, req: RoleChangeRequest) -> AdminUser:
    authorize(principal, Permission.USER_ROLE_ASSIGN)
    try:
        if farmer_id == principal.farmer_id:                   # also re-checked under lock
            raise AdminRejected("SELF_CHANGE", "You can't change your own role or account status.")
        return _user(await repo.set_role(principal, farmer_id, req.role, req.expected_role))
    except AdminRejected as exc:
        await _audit_failure(principal, "ROLE_CHANGED", "account", farmer_id, exc, {"to": req.role.value})
        raise


async def set_reviewer_approval(principal: Principal, farmer_id: str, approved: bool) -> AdminUser:
    """Approve / revoke a reviewer account (docs/HUMAN_REVIEW.md). Revoking signs it out."""
    authorize(principal, Permission.REVIEWER_APPROVE)
    action = "REVIEWER_APPROVED" if approved else "REVIEWER_APPROVAL_REVOKED"
    try:
        if farmer_id == principal.farmer_id:
            raise AdminRejected("SELF_CHANGE", "You can't change your own reviewer approval.")
        return _user(await repo.set_reviewer_approval(principal, farmer_id, approved))
    except AdminRejected as exc:
        await _audit_failure(principal, action, "account", farmer_id, exc)
        raise


async def change_status(principal: Principal, farmer_id: str, is_active: bool) -> AdminUser:
    authorize(principal, Permission.USER_STATUS_MANAGE)
    action = "ACCOUNT_REACTIVATED" if is_active else "ACCOUNT_DEACTIVATED"
    try:
        if farmer_id == principal.farmer_id:
            raise AdminRejected("SELF_CHANGE", "You can't change your own role or account status.")
        return _user(await repo.set_active(principal, farmer_id, is_active))
    except AdminRejected as exc:
        await _audit_failure(principal, action, "account", farmer_id, exc)
        raise


async def curate_scheme(principal: Principal, scheme_id: str, req: SchemeCurationRequest) -> SchemeCuration:
    authorize(principal, Permission.SCHEME_CURATE)
    changes = {f: getattr(req, f) for f in ("status", "needs_review", "review_notes")
               if f in req.model_fields_set}
    row = await repo.curate_scheme(principal, scheme_id, changes)
    if row is None:
        exc = AdminRejected("NOT_FOUND", "Scheme not found.")
        await _audit_failure(principal, "SCHEME_CURATED", "scheme", scheme_id, exc)
        raise exc
    return SchemeCuration(scheme_id=row.scheme_id, name=row.name, status=row.status,
                          needs_review=row.needs_review, review_notes=row.review_notes)


async def list_audit_events(principal: Principal, limit: int, offset: int, action: Optional[str] = None,
                            target_type: Optional[str] = None, target_id: Optional[str] = None,
                            actor: Optional[str] = None, outcome: Optional[str] = None,
                            correlation_id: Optional[str] = None, since: Optional[datetime] = None,
                            until: Optional[datetime] = None) -> AuditPage:
    authorize(principal, Permission.AUDIT_READ)
    rows, total = await audit_repo.list_page(limit, offset, action, target_type, target_id, actor,
                                             outcome, correlation_id, since, until)
    return AuditPage(items=[AuditEvent(
        id=r.id, occurred_at=r.occurred_at.isoformat(), actor_label=r.actor_label, actor_role=r.actor_role,
        action=r.action, target_type=r.target_type, target_id=r.target_id, details=r.details,
        ip_address=r.ip_address, outcome=r.outcome, correlation_id=r.correlation_id,
        entry_hash=r.entry_hash) for r in rows], total=total, limit=limit, offset=offset)


async def verify_audit_log(principal: Principal) -> AuditIntegrity:
    """Recompute the audit hash chain; the check itself is audited (with its result)."""
    authorize(principal, Permission.AUDIT_READ)
    result = await audit_repo.verify_chain()
    await audit_repo.record(principal, "AUDIT_VERIFIED", "audit_log", None,
                            {"valid": result["valid"], "checked": result["checked"],
                             "first_broken_id": result["first_broken_id"]},
                            outcome="SUCCESS" if result["valid"] else "FAILURE")
    return AuditIntegrity(**result, verified_at=datetime.now(timezone.utc).isoformat())
