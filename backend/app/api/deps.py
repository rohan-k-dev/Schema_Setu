"""
FastAPI dependencies for authentication (server-managed cookie sessions).

Usage in route handlers:
    from app.api.deps import get_current_farmer_id

    @router.get("/me")
    async def me(farmer_id: str = Depends(get_current_farmer_id)):
        ...

The session token travels only in the HttpOnly cookie. Because browsers attach
cookies automatically, every state-changing request (POST/PUT/PATCH/DELETE)
authenticated by the cookie must also carry the session's CSRF token in the
``X-CSRF-Token`` header (synchronizer-token pattern).
"""

import hmac
from typing import Optional

from fastapi import Depends, HTTPException, Request, status

from app.core.config import settings
from app.core.logging import get_logger
from app.core.permissions import Permission, PermissionDenied, Principal, authorize
from app.core.security import csrf_token_valid
from app.database.connection import is_db_available
from app.database.repositories import audit_repository as audit_repo
from app.services.auth_service import SessionContext, get_session

logger = get_logger(__name__)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
CSRF_HEADER = "X-CSRF-Token"


def _unauthorized(message: str = "Please sign in to continue.") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                         detail={"code": "NOT_AUTHENTICATED", "message": message})


def csrf_ok(request: Request, ctx: SessionContext) -> bool:
    if request.method in SAFE_METHODS:
        return True
    return csrf_token_valid(ctx.raw_token, request.headers.get(CSRF_HEADER))


async def get_current_session(request: Request) -> SessionContext:
    """The validated session of the signed-in user (401 otherwise; 403 on CSRF failure)."""
    if not is_db_available():
        raise HTTPException(status_code=503, detail={
            "code": "ACCOUNTS_UNAVAILABLE", "message": "Accounts are unavailable (no database)."})
    raw = request.cookies.get(settings.SESSION_COOKIE_NAME)
    ctx = await get_session(raw, request.headers.get("User-Agent"))
    if ctx is None:
        raise _unauthorized("Your session has expired. Please sign in again." if raw else
                            "Please sign in to continue.")
    request.state.session_ctx = ctx              # for ensure_recent_auth (sensitive actions)
    if not csrf_ok(request, ctx):
        logger.warning(f"CSRF check failed: {request.method} {request.url.path}")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={
            "code": "CSRF_FAILED", "message": "Security check failed. Refresh the page and try again."})
    return ctx


async def get_current_farmer_id(request: Request) -> str:
    """The signed-in farmer's UUID (``farmer_id``)."""
    return (await get_current_session(request)).farmer.farmer_id


# ─── Role-based access control (docs/RBAC.md) ─────────────────────────────────
#
# Routes declare what they need with require(permission) or require_own(permission);
# the role comes from the account row loaded with the session on every request (never
# from the client), so a role change or deactivation applies to the very next request.
# test_rbac.py fails if a non-public route has no such dependency (deny by default).

REVIEW_KEY_HEADER = "X-Review-Key"


def _ip(request: Request) -> Optional[str]:
    return request.client.host if request.client else None


def _forbidden(message: str = "You don't have permission to do this.") -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                         detail={"code": "FORBIDDEN", "message": message})


def _review_key_principal(request: Request) -> Principal:
    """
    The development-only shared reviewer key (phase 6 §68). It never acts for an account
    and has review permissions only; it is refused in production and when unset.
    """
    expected = settings.REVIEW_API_KEY
    given = request.headers.get(REVIEW_KEY_HEADER) or ""
    if (not expected or settings.ENVIRONMENT == "production"
            or not hmac.compare_digest(given.encode(), expected.encode())):
        raise _forbidden("Unauthorized reviewer access.")
    return Principal.review_key(_ip(request))


async def _record_denial(principal: Principal, permission: Permission, request: Request) -> None:
    """Audit a refused attempt by a signed-in account (best effort: never changes the answer)."""
    try:
        await audit_repo.record(principal, "ACCESS_DENIED", "endpoint", f"{request.method} {request.url.path}",
                                {"permission": permission.value}, outcome="DENIED")
    except Exception as exc:
        logger.warning(f"Could not audit a denied request: {type(exc).__name__}")


async def get_current_principal(request: Request) -> Principal:
    """The signed-in account as a Principal: 401 when not signed in, 403 on a CSRF failure."""
    if not request.cookies.get(settings.SESSION_COOKIE_NAME):
        raise _unauthorized()                            # no credentials at all: no lookup needed
    return Principal.for_account((await get_current_session(request)).farmer, _ip(request))


async def get_reviewer_principal(request: Request) -> Principal:
    """A signed-in account, or the development-only shared reviewer key when it is sent."""
    if REVIEW_KEY_HEADER in request.headers:
        return _review_key_principal(request)
    return await get_current_principal(request)


def require(permission: Permission, *, allow_review_key: bool = False):
    """
    Dependency: the request's Principal, if it holds *permission*. 401 when not signed in
    (403 on a CSRF failure), 403 when the role lacks the permission.
    """
    source = get_reviewer_principal if allow_review_key else get_current_principal

    async def dependency(request: Request, principal: Principal = Depends(source)) -> Principal:
        try:
            return authorize(principal, permission)
        except PermissionDenied:
            logger.warning(f"Denied {permission.value} to {principal.via}:{principal.role} "
                           f"{request.method} {request.url.path}")
            if principal.account_pk is not None:
                await _record_denial(principal, permission, request)
            raise _forbidden()

    dependency.required_permission = permission          # read by the deny-by-default route test
    return dependency


def ensure_recent_auth(request: Request, principal: Principal) -> None:
    """
    Sensitive actions (final review decisions, assignments, grants, reviewer approval) need a
    sign-in or password confirmation within REAUTH_WINDOW_MINUTES; otherwise 403 REAUTH_REQUIRED
    and the client asks for the password (POST /auth/reauthenticate). The development-only review
    key has no session and is exempt (it is refused in production).
    """
    if principal.via == "review_key":
        return
    from app.services.auth_service import recently_authenticated
    ctx = getattr(request.state, "session_ctx", None)
    if ctx is None or not recently_authenticated(ctx):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={
            "code": "REAUTH_REQUIRED", "message": "For your security, confirm your password to continue."})


def require_own(permission: Permission):
    """Dependency for self-service routes: the signed-in account's farmer_id, if permitted."""
    check = require(permission)

    async def dependency(principal: Principal = Depends(check)) -> str:
        return principal.farmer_id

    dependency.required_permission = permission
    return dependency


async def get_optional_farmer_id(request: Request) -> Optional[str]:
    """
    The signed-in farmer's UUID, or None for anonymous use (chat and voice work
    without an account). A missing/expired session or a failed CSRF check is
    treated as anonymous, so a cross-site request cannot act as the user.
    """
    raw = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not raw or not is_db_available():
        return None
    try:
        ctx = await get_session(raw, request.headers.get("User-Agent"))
    except Exception as exc:  # account store down: chat keeps working anonymously
        logger.warning(f"Session lookup failed, continuing anonymously: {type(exc).__name__}")
        return None
    if ctx is None or not csrf_ok(request, ctx):
        return None
    return ctx.farmer.farmer_id
