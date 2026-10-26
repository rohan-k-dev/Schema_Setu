"""
Auth service — account registration, e-mail verification, login, server-managed
sessions, logout, password reset and password change.

The HTTP layer (app/api/auth.py) calls these functions; all SQL lives in
app.database.repositories.auth_repository (imported as ``repo`` so tests can
substitute an in-memory store).

Security properties (see docs/AUTH.md):
- Argon2id password hashes; legacy bcrypt hashes upgraded at the next login.
- Sessions: random 256-bit token in an HttpOnly cookie; only its SHA-256 is stored.
  Idle timeout + absolute lifetime; bound to the browser's User-Agent; revoked on
  logout, password reset and password change; a fresh session id on every login.
- Generic responses for registration and recovery (no account enumeration);
  unknown accounts still cost one Argon2 verification (no timing oracle).
- Temporary account lock after repeated failed logins.
- Reset / verification tokens: random, hashed, single-use (atomic), short-lived;
  issuing a new one invalidates older ones.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import (
    generate_token,
    hash_password,
    hash_token,
    hash_user_agent,
    password_needs_rehash,
    verify_password,
)
from app.database.repositories import auth_repository as repo
from app.models.db.farmer_auth import AuthSessionRow, FarmerRow
from app.services import email_service

logger = get_logger(__name__)

GENERIC_LOGIN_ERROR = "Invalid email or password, or the account is temporarily locked."
TOUCH_INTERVAL = timedelta(seconds=60)


class AuthError(Exception):
    """An auth-layer rejection with an HTTP status and a client-safe message."""

    def __init__(self, message: str, code: str = "AUTH_ERROR", status: int = 400):
        self.message = message
        self.code = code
        self.status = status
        super().__init__(message)


@dataclass
class SessionContext:
    """A validated session for the current request."""
    raw_token: str
    session: AuthSessionRow
    farmer: FarmerRow


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


# ─── Registration and e-mail verification ────────────────────────────────────

async def register(email: str, password: str, full_name: Optional[str], phone: Optional[str]) -> None:
    """
    Create an unverified account and e-mail a verification link.

    Always succeeds from the caller's point of view: when the e-mail is already
    registered, the owner gets an "account exists" e-mail instead, and the API
    returns the same response (no account enumeration).
    """
    password_hash = hash_password(password)          # same cost on both paths
    farmer = await repo.create_farmer(email, password_hash, full_name, phone)
    if farmer is None:
        existing = await repo.get_farmer_by_email(email)
        if existing:
            await email_service.send_account_exists_email(existing.email)
        else:
            # Phone number already used by another account — same generic response.
            # No PII in the log: the caller cannot learn which contact detail collided.
            logger.info("Registration ignored: a contact detail is already in use.")
        return
    if settings.REQUIRE_EMAIL_VERIFICATION:
        await _send_verification(farmer)


async def _send_verification(farmer: FarmerRow) -> None:
    raw, token_hash = generate_token()
    expires = _now() + timedelta(hours=settings.EMAIL_VERIFY_EXPIRE_HOURS)
    await repo.create_token(farmer.id, repo.PURPOSE_VERIFY_EMAIL, token_hash, expires)
    await email_service.send_verification_email(farmer.email, raw)


async def verify_email(raw_token: str) -> None:
    if not await repo.verify_email_with_token(hash_token(raw_token)):
        raise AuthError("This verification link is invalid or has expired.", "INVALID_TOKEN", 400)


async def resend_verification(email: str) -> None:
    """Generic: sends a new link only for an existing, active, unverified account."""
    farmer = await repo.get_farmer_by_email(email)
    if farmer and farmer.is_active and not farmer.is_verified:
        await _send_verification(farmer)


# ─── Login, sessions, logout ─────────────────────────────────────────────────

async def login(email: str, password: str, user_agent: Optional[str],
                ip_address: Optional[str]) -> SessionContext:
    """
    Verify credentials and start a new session.

    Raises AuthError(401) with one generic message for unknown e-mail, wrong
    password and locked account. Account state (unverified, deactivated) is only
    revealed after a correct password.
    """
    farmer = await repo.get_farmer_by_email(email)
    password_ok = verify_password(password, farmer.password_hash if farmer else None)

    if farmer is None:
        raise AuthError(GENERIC_LOGIN_ERROR, "INVALID_CREDENTIALS", 401)
    if farmer.locked_until and farmer.locked_until > _now():
        raise AuthError(GENERIC_LOGIN_ERROR, "INVALID_CREDENTIALS", 401)
    if not password_ok:
        await repo.record_login_failure(farmer.id, settings.LOGIN_MAX_FAILURES,
                                        settings.LOGIN_LOCK_MINUTES)
        raise AuthError(GENERIC_LOGIN_ERROR, "INVALID_CREDENTIALS", 401)
    if not farmer.is_active:
        raise AuthError("This account has been deactivated. Contact support.", "ACCOUNT_INACTIVE", 403)
    if settings.REQUIRE_EMAIL_VERIFICATION and not farmer.is_verified:
        raise AuthError("Please verify your e-mail address first. Check your inbox for the link.",
                        "EMAIL_NOT_VERIFIED", 403)

    upgraded = hash_password(password) if password_needs_rehash(farmer.password_hash) else None
    await repo.record_login_success(farmer.id, upgraded)
    return await _start_session(farmer, user_agent, ip_address)


async def _start_session(farmer: FarmerRow, user_agent: Optional[str],
                         ip_address: Optional[str]) -> SessionContext:
    raw, session_hash = generate_token()
    expires = _now() + timedelta(hours=settings.SESSION_ABSOLUTE_HOURS)
    await repo.create_session(farmer.id, session_hash, hash_user_agent(user_agent),
                              ip_address, expires)
    now = _now()
    session = AuthSessionRow(id=0, farmer_id=farmer.id, session_hash=session_hash,
                             user_agent_hash=hash_user_agent(user_agent), ip_address=ip_address,
                             created_at=now, last_seen_at=now, expires_at=expires)
    return SessionContext(raw, session, farmer)


async def get_session(raw_token: Optional[str], user_agent: Optional[str]) -> Optional[SessionContext]:
    """
    Validate a session cookie. Returns None (and revokes the session where useful)
    when it is unknown, revoked, past its absolute or idle expiry, used from a
    different browser (User-Agent mismatch — likely a stolen cookie), or the
    account is deactivated.
    """
    if not raw_token or len(raw_token) > 200:
        return None
    session_hash = hash_token(raw_token)
    found = await repo.get_live_session(session_hash)
    if not found:
        return None
    session, farmer = found
    now = _now()
    if session.user_agent_hash != hash_user_agent(user_agent):
        logger.warning(f"Session {session.id} used from a different browser — revoked")
        await repo.revoke_session(session_hash, "user_agent_mismatch")
        return None
    staff = is_staff(farmer)
    idle = settings.STAFF_SESSION_IDLE_MINUTES if staff else settings.SESSION_IDLE_MINUTES
    if session.last_seen_at + timedelta(minutes=idle) <= now:
        await repo.revoke_session(session_hash, "idle_timeout")
        return None
    if staff and session.created_at + timedelta(hours=settings.STAFF_SESSION_ABSOLUTE_HOURS) <= now:
        await repo.revoke_session(session_hash, "staff_session_expired")     # shorter lifetime for staff
        return None
    if not farmer.is_active:
        return None
    if now - session.last_seen_at >= TOUCH_INTERVAL:
        await repo.touch_session(session.id)
    return SessionContext(raw_token, session, farmer)


def is_staff(farmer: FarmerRow) -> bool:
    """REVIEWER and ADMIN accounts get shorter sessions (docs/HUMAN_REVIEW.md, Access policy)."""
    return getattr(farmer, "role", "FARMER") in ("REVIEWER", "ADMIN")


def recently_authenticated(ctx: SessionContext) -> bool:
    """Signed in, or password re-entered, within REAUTH_WINDOW_MINUTES."""
    last = max(t for t in (ctx.session.created_at, ctx.session.reauthenticated_at) if t is not None)
    return _now() - last <= timedelta(minutes=settings.REAUTH_WINDOW_MINUTES)


REAUTH_MAX_FAILURES = 5


async def reauthenticate(ctx: SessionContext, password: str) -> None:
    """
    Confirm the password for a sensitive action. Wrong passwords are counted per session;
    after REAUTH_MAX_FAILURES the session is ended (someone else may be at the keyboard).
    """
    from app.core.rate_limit import limiter
    key = f"session:{ctx.session.id}"
    if not verify_password(password, ctx.farmer.password_hash):
        if limiter.hit("reauth_fail", key, REAUTH_MAX_FAILURES - 1, 900) is not None:
            await repo.revoke_session(ctx.session.session_hash, "reauth_failures")
            raise AuthError("Too many wrong passwords. Please sign in again.", "SESSION_ENDED", 401)
        raise AuthError("That password is not correct.", "INVALID_PASSWORD", 400)
    await repo.mark_reauthenticated(ctx.session.id)


async def logout(raw_token: Optional[str]) -> None:
    if raw_token and len(raw_token) <= 200:
        await repo.revoke_session(hash_token(raw_token), "logout")


async def logout_all(ctx: SessionContext) -> int:
    return await repo.revoke_all_sessions(ctx.farmer.id, "logout_all")


# ─── Password reset and change ───────────────────────────────────────────────

async def forgot_password(email: str) -> None:
    """Generic: e-mails a 30-minute single-use reset link only if the account exists."""
    farmer = await repo.get_farmer_by_email(email)
    if not farmer or not farmer.is_active:
        return
    raw, token_hash = generate_token()
    expires = _now() + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES)
    await repo.create_token(farmer.id, repo.PURPOSE_RESET_PASSWORD, token_hash, expires)
    await email_service.send_password_reset_email(farmer.email, raw)


async def reset_password(raw_token: str, new_password: str) -> None:
    """Consume the token, set the password and sign the account out everywhere."""
    pk = await repo.reset_password_with_token(hash_token(raw_token), hash_password(new_password))
    if pk is None:
        raise AuthError("This reset link is invalid or has expired. Request a new one.",
                        "INVALID_TOKEN", 400)
    farmer = await repo.get_farmer_by_pk(pk)
    if farmer:
        await email_service.send_password_changed_email(farmer.email)


async def change_password(ctx: SessionContext, current_password: str, new_password: str,
                          user_agent: Optional[str], ip_address: Optional[str]) -> SessionContext:
    """Verify the current password, set the new one, revoke all sessions, start a new one."""
    if not verify_password(current_password, ctx.farmer.password_hash):
        raise AuthError("Current password is incorrect.", "INVALID_CURRENT_PASSWORD", 400)
    await repo.change_password(ctx.farmer.id, hash_password(new_password))
    await email_service.send_password_changed_email(ctx.farmer.email)
    return await _start_session(ctx.farmer, user_agent, ip_address)
