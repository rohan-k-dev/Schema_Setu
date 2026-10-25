"""
Security utilities — password hashing and JWT token management.

All cryptographic operations are centralised here.
The rest of the codebase MUST call these helpers and MUST NOT use
passlib or jose directly.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
import bcrypt

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ─── Password hashing ────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Return a bcrypt hash of *plain* using native bcrypt with salt."""
    plain_bytes = plain.encode("utf-8")[:72]
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(plain_bytes, salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches *hashed* (constant-time)."""
    try:
        plain_bytes = plain.encode("utf-8")[:72]
        hashed_bytes = hashed.encode("utf-8")
        return bcrypt.checkpw(plain_bytes, hashed_bytes)
    except Exception as exc:
        logger.debug(f"verify_password exception: {exc}")
        return False


# ─── JWT access tokens ───────────────────────────────────────────────────────

def create_access_token(
    farmer_id: str,
    *,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a short-lived JWT access token.

    The token carries the farmer's UUID as the ``sub`` claim and an
    ``exp`` claim set to *now + ACCESS_TOKEN_EXPIRE_MINUTES* by default.
    """
    expire = datetime.now(tz=timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub": farmer_id,
        "exp": expire,
        "iat": datetime.now(tz=timezone.utc),
        "type": "access",
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[str]:
    """
    Decode and validate a JWT access token.

    Returns the farmer UUID (``sub`` claim) on success, None on any failure.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        if payload.get("type") != "access":
            return None
        return payload.get("sub")
    except JWTError as exc:
        logger.debug(f"JWT decode failed: {exc}")
        return None


# ─── Refresh tokens (opaque, stored hashed in DB) ───────────────────────────

def generate_refresh_token() -> tuple[str, str]:
    """
    Generate a cryptographically random refresh token.

    Returns ``(raw_token, hashed_token)``.
    Store only the hash in the database; send the raw token to the client.
    """
    raw = secrets.token_urlsafe(48)
    hashed = _hash_opaque(raw)
    return raw, hashed


def hash_refresh_token(raw: str) -> str:
    """SHA-256 hash of a raw refresh token for DB lookup."""
    return _hash_opaque(raw)


def _hash_opaque(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# ─── Password-reset tokens (short-lived, opaque) ─────────────────────────────

def generate_reset_token() -> tuple[str, str]:
    """
    Generate a cryptographically random password-reset token.

    Returns ``(raw_token, hashed_token)``.
    Send the raw token to the user; store the hash in the DB.
    """
    raw = secrets.token_urlsafe(32)
    hashed = _hash_opaque(raw)
    return raw, hashed
