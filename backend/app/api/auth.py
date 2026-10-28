"""
Auth API — registration, e-mail verification, login, session, logout,
password reset and password change. All endpoints are under /auth.

Sessions are server-managed: the session token is set as an HttpOnly cookie
(Secure in production, SameSite=Lax) and never appears in a response body.
State-changing requests made with the cookie must send the CSRF token from
/auth/login or /auth/session in the X-CSRF-Token header.

Every endpoint is rate-limited (HTTP 429 + Retry-After). POST requests from a
browser origin that is not in CORS_ORIGINS are rejected (403).
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import csrf_ok, get_current_principal, get_current_session
from app.core.config import settings
from app.core.permissions import Principal
from app.models.rbac_schemas import MyAccess
from app.core.logging import get_logger
from app.core.rate_limit import LIMITS, limiter
from app.core.security import csrf_token_for
from app.database.connection import is_db_available
from app.models.auth_schemas import (
    AuthUser,
    ChangePasswordRequest,
    EmailOnlyRequest,
    LoginRequest,
    MessageResponse,
    ReauthRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SessionResponse,
    VerifyEmailRequest,
)
from app.services import auth_service
from app.services.auth_service import AuthError, SessionContext

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])

REGISTER_MESSAGE = ("If this e-mail can be used, we have sent a verification link to it. "
                    "Open the link to activate your account, then sign in.")
REGISTER_MESSAGE_NO_VERIFY = ("If this e-mail can be used, the account is ready — "
                              "you can sign in now.")
RECOVERY_MESSAGE = "If an account exists for this e-mail, we have sent a link to it."


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _rate_limit(bucket: str, key: str) -> None:
    limit, window = LIMITS[bucket]
    retry_after = limiter.hit(bucket, key.lower(), limit, window)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={"code": "RATE_LIMITED",
                    "message": "Too many attempts. Please wait a few minutes and try again."},
            headers={"Retry-After": str(retry_after)},
        )


async def trusted_origin(request: Request) -> None:
    """Reject cross-site browser POSTs (login CSRF, etc.). Non-browser clients send no Origin."""
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in {o.rstrip("/") for o in settings.CORS_ORIGINS}:
        raise HTTPException(status_code=403, detail={
            "code": "ORIGIN_NOT_ALLOWED", "message": "Request origin is not allowed."})


async def accounts_available() -> None:
    if not is_db_available():
        raise HTTPException(status_code=503, detail={
            "code": "ACCOUNTS_UNAVAILABLE",
            "message": "Accounts are unavailable right now. You can still use the assistant without signing in."})


def _error(exc: AuthError) -> JSONResponse:
    return JSONResponse(status_code=exc.status,
                        content={"error": {"code": exc.code, "message": exc.message}})


def _set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=settings.SESSION_ABSOLUTE_HOURS * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=settings.SESSION_COOKIE_NAME, path="/", httponly=True,
                           secure=settings.cookie_secure, samesite="lax")


def _session_body(ctx: SessionContext) -> SessionResponse:
    f = ctx.farmer
    return SessionResponse(
        user=AuthUser(farmer_id=f.farmer_id, email=f.email, full_name=f.full_name,
                      is_verified=f.is_verified, role=f.role),
        csrf_token=csrf_token_for(ctx.raw_token),
        session_expires_at=ctx.session.expires_at.isoformat(),
    )


_GUARDS = [Depends(trusted_origin), Depends(accounts_available)]


# ─── Registration and e-mail verification ────────────────────────────────────

@router.post("/register", status_code=status.HTTP_202_ACCEPTED, response_model=MessageResponse,
             dependencies=_GUARDS, summary="Create an account (e-mails a verification link)")
async def register(req: RegisterRequest, request: Request) -> MessageResponse:
    """Same response whether or not the e-mail is already registered (no enumeration)."""
    _rate_limit("register_ip", _client_ip(request))
    await auth_service.register(req.email, req.password, req.full_name, req.phone)
    message = REGISTER_MESSAGE if settings.REQUIRE_EMAIL_VERIFICATION else REGISTER_MESSAGE_NO_VERIFY
    return MessageResponse(message=message)


@router.post("/verify-email", response_model=MessageResponse, dependencies=_GUARDS,
             summary="Confirm an e-mail address with the link token")
async def verify_email(req: VerifyEmailRequest, request: Request):
    _rate_limit("token_ip", _client_ip(request))
    try:
        await auth_service.verify_email(req.token)
    except AuthError as exc:
        return _error(exc)
    return MessageResponse(message="Your e-mail is verified. You can sign in now.")


@router.post("/resend-verification", status_code=status.HTTP_202_ACCEPTED,
             response_model=MessageResponse, dependencies=_GUARDS,
             summary="Send a new verification link")
async def resend_verification(req: EmailOnlyRequest, request: Request) -> MessageResponse:
    _rate_limit("forgot_ip", _client_ip(request))
    _rate_limit("resend_email", req.email)
    await auth_service.resend_verification(req.email)
    return MessageResponse(message=RECOVERY_MESSAGE)


# ─── Login, session, logout ──────────────────────────────────────────────────

@router.post("/login", response_model=SessionResponse, dependencies=_GUARDS,
             summary="Sign in (sets the HttpOnly session cookie)")
async def login(req: LoginRequest, request: Request, response: Response):
    _rate_limit("login_ip", _client_ip(request))
    _rate_limit("login_email", req.email)
    # Session fixation: whatever session the browser presented is ended; a new id is issued.
    await auth_service.logout(request.cookies.get(settings.SESSION_COOKIE_NAME))
    try:
        ctx = await auth_service.login(req.email, req.password,
                                       request.headers.get("User-Agent"), _client_ip(request))
    except AuthError as exc:
        err = _error(exc)
        _clear_session_cookie(err)
        return err
    _set_session_cookie(response, ctx.raw_token)
    return _session_body(ctx)


@router.get("/session", response_model=SessionResponse,
            summary="The current session's user and CSRF token (401 when signed out)")
async def current_session(ctx: SessionContext = Depends(get_current_session)) -> SessionResponse:
    return _session_body(ctx)


@router.get("/permissions", response_model=MyAccess,
            summary="Your role and permissions (for showing links; every check is on the server)")
async def my_permissions(principal: Principal = Depends(get_current_principal)) -> MyAccess:
    return MyAccess(role=principal.role.value if principal.role else "NONE",
                    permissions=sorted(p.value for p in principal.permissions))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, dependencies=_GUARDS,
             summary="End this session (always clears the cookie)")
async def logout(request: Request):
    raw = request.cookies.get(settings.SESSION_COOKIE_NAME)
    ctx = await auth_service.get_session(raw, request.headers.get("User-Agent"))
    if ctx is not None:
        if not csrf_ok(request, ctx):
            raise HTTPException(status_code=403, detail={
                "code": "CSRF_FAILED", "message": "Security check failed. Refresh the page and try again."})
        await auth_service.logout(ctx.raw_token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_session_cookie(response)
    return response


@router.post("/logout-all", response_model=MessageResponse, dependencies=_GUARDS,
             summary="End every session of this account (all devices)")
async def logout_all(response: Response, ctx: SessionContext = Depends(get_current_session)):
    count = await auth_service.logout_all(ctx)
    _clear_session_cookie(response)
    return MessageResponse(message=f"Signed out of {count} session(s).")


# ─── Password reset and change ───────────────────────────────────────────────

@router.post("/forgot-password", status_code=status.HTTP_202_ACCEPTED,
             response_model=MessageResponse, dependencies=_GUARDS,
             summary="E-mail a password-reset link (generic response)")
async def forgot_password(req: EmailOnlyRequest, request: Request) -> MessageResponse:
    _rate_limit("forgot_ip", _client_ip(request))
    _rate_limit("forgot_email", req.email)
    await auth_service.forgot_password(req.email)
    return MessageResponse(message=RECOVERY_MESSAGE)


@router.post("/reset-password", response_model=MessageResponse, dependencies=_GUARDS,
             summary="Set a new password with a reset link token (signs out everywhere)")
async def reset_password(req: ResetPasswordRequest, request: Request, response: Response):
    _rate_limit("token_ip", _client_ip(request))
    try:
        await auth_service.reset_password(req.token, req.new_password)
    except AuthError as exc:
        return _error(exc)
    _clear_session_cookie(response)
    return MessageResponse(message="Your password has been changed. Please sign in with the new password.")


@router.post("/reauthenticate", dependencies=_GUARDS,
             summary="Confirm your password before a sensitive action (review decisions, assignments, approvals)")
async def reauthenticate(req: ReauthRequest, request: Request, ctx: SessionContext = Depends(get_current_session)):
    """
    Sensitive staff actions need a sign-in or password confirmation within REAUTH_WINDOW_MINUTES
    (docs/HUMAN_REVIEW.md). Five wrong passwords end the session.
    """
    from app.core.permissions import Principal
    from app.database.repositories import audit_repository
    principal = Principal.for_account(ctx.farmer, _client_ip(request))
    try:
        await auth_service.reauthenticate(ctx, req.password)
    except AuthError as exc:
        try:
            await audit_repository.record(principal, "REAUTHENTICATION", "account", ctx.farmer.farmer_id,
                                          {"result": exc.code}, outcome="FAILURE")
        except Exception:
            logger.warning("Could not audit a failed reauthentication")
        if exc.code == "SESSION_ENDED":
            response = _error(exc)
            response.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
            return response
        return _error(exc)
    try:
        await audit_repository.record(principal, "REAUTHENTICATION", "account", ctx.farmer.farmer_id, {})
    except Exception:
        logger.warning("Could not audit a reauthentication")
    return {"reauthenticated": True, "valid_for_minutes": settings.REAUTH_WINDOW_MINUTES}


@router.post("/change-password", response_model=SessionResponse, dependencies=_GUARDS,
             summary="Change password while signed in (other sessions are signed out)")
async def change_password(req: ChangePasswordRequest, request: Request, response: Response,
                          ctx: SessionContext = Depends(get_current_session)):
    _rate_limit("change_password", ctx.farmer.farmer_id)
    try:
        new_ctx = await auth_service.change_password(ctx, req.current_password, req.new_password,
                                                     request.headers.get("User-Agent"),
                                                     _client_ip(request))
    except AuthError as exc:
        return _error(exc)
    _set_session_cookie(response, new_ctx.raw_token)
    return _session_body(new_ctx)
