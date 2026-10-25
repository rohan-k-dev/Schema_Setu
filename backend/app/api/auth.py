"""
Auth API — farmer registration, login, token refresh, logout,
and password reset endpoints.

All endpoints are under /auth prefix.
"""

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.models.auth_schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
)
from app.services.auth_service import (
    AuthError,
    complete_password_reset,
    login_farmer,
    logout_farmer,
    refresh_tokens,
    register_farmer,
    request_password_reset,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _auth_error_response(exc: AuthError) -> JSONResponse:
    """Convert AuthError to a structured JSON 400/401 response."""
    status_code = (
        status.HTTP_401_UNAUTHORIZED
        if exc.code in ("INVALID_CREDENTIALS", "INVALID_REFRESH_TOKEN", "INVALID_RESET_TOKEN")
        else status.HTTP_400_BAD_REQUEST
    )
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new farmer account",
)
async def register(req: RegisterRequest) -> TokenResponse:
    """
    Create a new farmer account.

    - Email must be unique.
    - Password must be ≥ 8 characters and contain at least one letter and one digit.
    - Returns a JWT access token + refresh token pair on success.
    """
    try:
        return await register_farmer(req)
    except AuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT if exc.code == "EMAIL_TAKEN"
            else status.HTTP_400_BAD_REQUEST,
            detail={"code": exc.code, "message": exc.message},
        )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Sign in and receive tokens",
)
async def login(req: LoginRequest, request: Request) -> TokenResponse:
    """
    Authenticate with email + password.

    Returns a short-lived JWT access token and a long-lived opaque refresh token.
    Store the refresh token securely (httpOnly cookie recommended on the client).
    """
    try:
        user_agent = request.headers.get("User-Agent")
        ip = request.client.host if request.client else None
        return await login_farmer(req, user_agent=user_agent, ip_address=ip)
    except AuthError as exc:
        return _auth_error_response(exc)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Rotate the access + refresh token pair",
)
async def refresh(req: RefreshRequest, request: Request) -> TokenResponse:
    """
    Exchange a valid refresh token for a new access + refresh token pair
    (refresh token rotation — the old refresh token is revoked immediately).
    """
    try:
        user_agent = request.headers.get("User-Agent")
        ip = request.client.host if request.client else None
        return await refresh_tokens(req.refresh_token, user_agent=user_agent, ip_address=ip)
    except AuthError as exc:
        return _auth_error_response(exc)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke the current refresh token (sign out)",
)
async def logout(req: RefreshRequest) -> None:
    """
    Revoke the supplied refresh token.

    The access token remains valid until expiry — clients should discard it.
    """
    await logout_farmer(req.refresh_token)


@router.post(
    "/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a password-reset link",
)
async def forgot_password(req: ForgotPasswordRequest):
    """
    Trigger a password-reset flow for the given email.

    Always returns 202 regardless of whether the email is registered
    (prevents email enumeration).

    In production, send the reset token to the user's email via your
    email service. For now the raw token is returned in the response
    for development/testing only.
    """
    raw_token = await request_password_reset(req)
    # In production, send raw_token via email — never expose it in the response.
    # We include it here for local development convenience only.
    return {
        "message": "If that email is registered, a reset link has been sent.",
        "_dev_token": raw_token,  # Remove this in production!
    }


@router.post(
    "/reset-password",
    status_code=status.HTTP_200_OK,
    summary="Complete password reset with token",
)
async def reset_password(req: ResetPasswordRequest):
    """
    Validate the reset token and update the password.

    The token is single-use and expires after PASSWORD_RESET_EXPIRE_HOURS.
    """
    try:
        await complete_password_reset(req)
        return {"message": "Password updated successfully. Please log in with your new password."}
    except AuthError as exc:
        return _auth_error_response(exc)
