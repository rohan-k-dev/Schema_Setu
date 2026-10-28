"""
Administrator API — accounts, scheme curation flags, audit log (docs/RBAC.md).

Every route requires a signed-in ADMIN (role from the database, checked on the
server in the dependency AND again in app.services.admin_service). PATCH routes
also need the X-CSRF-Token header. There is no route that changes the caller's own
role or status, and none that creates the first administrator: that is done on the
server with scripts/set_role.py.
"""

from datetime import datetime
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from app.api.deps import ensure_recent_auth, require
from app.core.exceptions import ConfigurationError, DatabaseError
from app.core.permissions import Permission, Principal, Role
from app.models.rbac_schemas import (
    ReviewerApprovalRequest,
    AdminUser,
    AdminUserPage,
    AuditIntegrity,
    AuditPage,
    RoleChangeRequest,
    SchemeCuration,
    SchemeCurationRequest,
    StatusChangeRequest,
)
from app.services import admin_service as svc

router = APIRouter(prefix="/admin", tags=["Administration"])

AccountIdPath = Annotated[str, Path(min_length=1, max_length=36, pattern=r"^[A-Za-z0-9\-]+$")]
SchemeIdPath = Annotated[str, Path(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_\-]+$")]

_STATUS = {
    "NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "SELF_CHANGE": status.HTTP_403_FORBIDDEN,
    "LAST_ADMIN": status.HTTP_409_CONFLICT,
    "CONFLICT": status.HTTP_409_CONFLICT,
    "NOT_A_REVIEWER": status.HTTP_422_UNPROCESSABLE_ENTITY,
    "NOT_ELIGIBLE": status.HTTP_422_UNPROCESSABLE_ENTITY,
}


async def _call(coro):
    try:
        return await coro
    except svc.AdminRejected as exc:
        raise HTTPException(status_code=_STATUS.get(exc.code, 400),
                            detail={"code": exc.code, "message": exc.message})
    except (DatabaseError, ConfigurationError):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={
            "code": "ADMIN_UNAVAILABLE", "message": "Administration is unavailable right now."})


@router.get("/users", response_model=AdminUserPage, summary="List accounts (metadata only)")
async def list_users(
    role: Optional[Role] = None,
    q: Optional[str] = Query(default=None, max_length=100, description="Part of an e-mail or name"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
    principal: Principal = Depends(require(Permission.USER_READ)),
) -> AdminUserPage:
    return await _call(svc.list_users(principal, limit, offset, role.value if role else None, q))


@router.get("/users/{farmer_id}", response_model=AdminUser, summary="One account (metadata only)")
async def get_user(
    farmer_id: AccountIdPath,
    principal: Principal = Depends(require(Permission.USER_READ)),
) -> AdminUser:
    return await _call(svc.get_user(principal, farmer_id))


@router.patch("/users/{farmer_id}/role", response_model=AdminUser, summary="Change another account's role")
async def change_role(
    req: RoleChangeRequest,
    farmer_id: AccountIdPath,
    principal: Principal = Depends(require(Permission.USER_ROLE_ASSIGN)),
) -> AdminUser:
    """Not your own (403); never the last active administrator (409). Signs the account out everywhere."""
    return await _call(svc.change_role(principal, farmer_id, req))


@router.patch("/users/{farmer_id}/status", response_model=AdminUser,
              summary="Deactivate / reactivate another account")
async def change_status(
    req: StatusChangeRequest,
    farmer_id: AccountIdPath,
    principal: Principal = Depends(require(Permission.USER_STATUS_MANAGE)),
) -> AdminUser:
    """Not your own (403); never the last active administrator (409). Deactivating signs it out."""
    return await _call(svc.change_status(principal, farmer_id, req.is_active))


@router.patch("/users/{farmer_id}/reviewer-approval", response_model=AdminUser,
              summary="Approve / revoke a REVIEWER account for review work (needs a recent sign-in)")
async def reviewer_approval(
    req: ReviewerApprovalRequest,
    farmer_id: AccountIdPath,
    request: Request,
    principal: Principal = Depends(require(Permission.REVIEWER_APPROVE)),
) -> AdminUser:
    """
    The REVIEWER role alone gives no access to review cases; an administrator approves the account
    here (docs/HUMAN_REVIEW.md). Revoking ends its sessions and case grants. Not your own account.
    """
    ensure_recent_auth(request, principal)
    return await _call(svc.set_reviewer_approval(principal, farmer_id, req.approved))


@router.patch("/schemes/{scheme_id}", response_model=SchemeCuration, summary="Scheme curation flags")
async def curate_scheme(
    req: SchemeCurationRequest,
    scheme_id: SchemeIdPath,
    principal: Principal = Depends(require(Permission.SCHEME_CURATE)),
) -> SchemeCuration:
    """
    Suspend / reactivate a scheme or flag it for curation. Rules and other content are
    not editable through the API (they belong to the corpus curation process).
    """
    return await _call(svc.curate_scheme(principal, scheme_id, req))


_TOKEN = r"^[A-Za-z0-9_.:\- ]+$"


@router.get("/audit-events", response_model=AuditPage, summary="The audit log (newest first, paginated)")
async def audit_events(
    action: Optional[str] = Query(default=None, max_length=40, pattern=r"^[A-Z_]+$"),
    target_type: Optional[str] = Query(default=None, max_length=30, pattern=r"^[a-z_]+$"),
    target_id: Optional[str] = Query(default=None, max_length=100, pattern=_TOKEN),
    actor: Optional[str] = Query(default=None, max_length=255),
    outcome: Optional[Literal["SUCCESS", "FAILURE", "DENIED"]] = None,
    correlation_id: Optional[str] = Query(default=None, max_length=64, pattern=r"^[A-Za-z0-9._\-]+$"),
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=1_000_000),
    principal: Principal = Depends(require(Permission.AUDIT_READ)),
) -> AuditPage:
    if since and until and since >= until:
        raise HTTPException(status_code=422, detail={"code": "BAD_RANGE", "message": "since must be before until."})
    return await _call(svc.list_audit_events(principal, limit, offset, action, target_type, target_id, actor,
                                             outcome, correlation_id, since, until))


@router.get("/audit-events/verify", response_model=AuditIntegrity,
            summary="Recompute the audit log's hash chain (tamper check)")
async def verify_audit_events(
    principal: Principal = Depends(require(Permission.AUDIT_READ)),
) -> AuditIntegrity:
    return await _call(svc.verify_audit_log(principal))
