"""
Auth service — business logic for farmer registration, login,
token management, and password reset.

The HTTP layer (app/api/auth.py) calls these functions.
The repository layer handles all SQL.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import (
    hash_password,
    verify_password,
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
    generate_reset_token,
    _hash_opaque as hash_opaque,
)
from app.database.repositories.farmer_repository import (
    get_farmer_by_email,
    get_farmer_by_id,
    get_farmer_pk,
    create_farmer,
    update_farmer_last_login,
    set_password_reset_token,
    get_farmer_by_reset_token,
    update_password,
    create_refresh_token,
    get_refresh_token,
    revoke_refresh_token,
    revoke_all_refresh_tokens,
)
from app.models.auth_schemas import (
    RegisterRequest,
    LoginRequest,
    TokenResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from app.models.db.farmer_auth import FarmerRow

logger = get_logger(__name__)


class AuthError(Exception):
    """Raised for all auth-layer rejections (wrong password, duplicate email, etc.)."""
    def __init__(self, message: str, code: str = "AUTH_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


# ─── Registration ─────────────────────────────────────────────────────────────

async def register_farmer(req: RegisterRequest) -> TokenResponse:
    """
    Create a new farmer account and return an initial token pair.

    Raises AuthError if the email is already registered.
    """
    existing = await get_farmer_by_email(req.email)
    if existing:
        raise AuthError("An account with this email already exists.", "EMAIL_TAKEN")

    pw_hash = hash_password(req.password)
    farmer = await create_farmer(
        email=req.email,
        password_hash=pw_hash,
        full_name=req.full_name,
        phone=req.phone,
    )
    if not farmer:
        raise AuthError("Account creation failed. Please try again.", "REGISTRATION_FAILED")

    return await _issue_token_pair(farmer, user_agent=None, ip_address=None)


# ─── Login ────────────────────────────────────────────────────────────────────

async def login_farmer(
    req: LoginRequest,
    user_agent: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> TokenResponse:
    """
    Validate credentials and return a fresh token pair.

    Uses a constant-time comparison to prevent timing attacks.
    Raises AuthError for invalid credentials or inactive accounts.
    """
    farmer = await get_farmer_by_email(req.email)
    # Always run verify_password even when farmer is None so response time
    # is consistent regardless of whether the email exists.
    _dummy_hash = "$2b$12$dummy_hash_for_constant_time_check_xxxxxxxxxxxxxxxxxxx"
    pw_ok = verify_password(req.password, farmer.password_hash if farmer else _dummy_hash)

    if not farmer or not pw_ok:
        raise AuthError("Invalid email or password.", "INVALID_CREDENTIALS")

    if not farmer.is_active:
        raise AuthError("Your account has been deactivated. Contact support.", "ACCOUNT_INACTIVE")

    await update_farmer_last_login(farmer.farmer_id)
    return await _issue_token_pair(farmer, user_agent=user_agent, ip_address=ip_address)


# ─── Token refresh ────────────────────────────────────────────────────────────

async def refresh_tokens(
    raw_refresh_token: str,
    user_agent: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> TokenResponse:
    """
    Rotate the token pair: revoke the old refresh token and issue a new pair.

    Raises AuthError if the refresh token is invalid, expired, or revoked.
    """
    token_hash = hash_refresh_token(raw_refresh_token)
    stored = await get_refresh_token(token_hash)
    if not stored:
        raise AuthError("Refresh token is invalid or has expired.", "INVALID_REFRESH_TOKEN")

    farmer = await _farmer_by_pk(stored.farmer_id)
    if not farmer or not farmer.is_active:
        raise AuthError("Account not found or inactive.", "ACCOUNT_INACTIVE")

    # Revoke old token (rotation)
    await revoke_refresh_token(token_hash)
    return await _issue_token_pair(farmer, user_agent=user_agent, ip_address=ip_address)


# ─── Logout ───────────────────────────────────────────────────────────────────

async def logout_farmer(raw_refresh_token: str) -> None:
    """Revoke the supplied refresh token (single device logout)."""
    token_hash = hash_refresh_token(raw_refresh_token)
    await revoke_refresh_token(token_hash)


async def logout_all_devices(farmer_id: str) -> None:
    """Revoke all refresh tokens for the farmer (all device logout)."""
    pk = await get_farmer_pk(farmer_id)
    if pk:
        await revoke_all_refresh_tokens(pk)


# ─── Password reset ───────────────────────────────────────────────────────────

async def request_password_reset(req: ForgotPasswordRequest) -> Optional[str]:
    """
    Generate a password-reset token for the given email.

    Returns the *raw* token (to be emailed to the user) or None if the
    email is not registered. The caller should always return a generic
    success response to prevent email enumeration.
    """
    farmer = await get_farmer_by_email(req.email)
    if not farmer:
        # Return None silently — do not leak whether the email is registered
        return None

    raw_token, token_hash = generate_reset_token()
    expires_at = datetime.now(tz=timezone.utc) + timedelta(
        hours=settings.PASSWORD_RESET_EXPIRE_HOURS
    )
    await set_password_reset_token(farmer.farmer_id, token_hash, expires_at)
    return raw_token


async def complete_password_reset(req: ResetPasswordRequest) -> None:
    """
    Validate a reset token and update the password.

    Raises AuthError if the token is invalid or expired.
    """
    token_hash = hash_opaque(req.token)
    farmer = await get_farmer_by_reset_token(token_hash)
    if not farmer:
        raise AuthError("Reset token is invalid or has expired.", "INVALID_RESET_TOKEN")

    new_hash = hash_password(req.new_password)
    await update_password(farmer.farmer_id, new_hash)


# ─── Internal helpers ─────────────────────────────────────────────────────────

async def _issue_token_pair(
    farmer: FarmerRow,
    *,
    user_agent: Optional[str],
    ip_address: Optional[str],
) -> TokenResponse:
    """Create an access token + refresh token pair and persist the refresh token."""
    access_token = create_access_token(farmer.farmer_id)
    raw_refresh, refresh_hash = generate_refresh_token()

    expires_at = datetime.now(tz=timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    farmer_pk = await get_farmer_pk(farmer.farmer_id)
    if farmer_pk:
        await create_refresh_token(
            farmer_pk=farmer_pk,
            token_hash=refresh_hash,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        farmer_id=farmer.farmer_id,
    )


async def _farmer_by_pk(pk: int) -> Optional[FarmerRow]:
    """Look up a farmer by integer PK via a sub-query."""
    from app.database.connection import get_db_connection, is_db_available
    from psycopg.rows import dict_row

    if not is_db_available():
        return None
    try:
        async with get_db_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT * FROM farmers WHERE id = %s", (pk,))
                row = await cur.fetchone()
                return FarmerRow(**row) if row else None
    except Exception as exc:
        logger.error(f"_farmer_by_pk failed: {exc}")
        return None
