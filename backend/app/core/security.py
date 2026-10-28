"""
Security utilities — password hashing, opaque tokens and CSRF tokens.

All cryptographic operations are centralised here; the rest of the codebase
MUST call these helpers and MUST NOT use argon2 / bcrypt / secrets directly.

Passwords: Argon2id (argon2-cffi) with the OWASP-recommended baseline
(m=19 MiB, t=2, p=1). Hashes made by the earlier bcrypt implementation are still
verified and are transparently upgraded to Argon2id at the next successful login
(see ``password_needs_rehash``).

Sessions, email-verification and password-reset tokens are opaque random values
(``secrets.token_urlsafe``). Only their SHA-256 hash is stored; the raw value is
given to the browser (HttpOnly cookie) or e-mailed to the user.
"""

import hashlib
import hmac
import secrets

import bcrypt
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ─── Password hashing ────────────────────────────────────────────────────────

_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=19_456,      # KiB (19 MiB) — OWASP Password Storage Cheat Sheet baseline
    parallelism=1,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

# Verified against when the e-mail is unknown, so a login for an unknown account
# costs the same as one for a real account (no account enumeration by timing).
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def hash_password(plain: str) -> str:
    """Return an Argon2id hash of *plain* (salted; encodes its own parameters)."""
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str | None) -> bool:
    """
    Return True if *plain* matches *hashed*.

    Accepts Argon2id hashes and legacy bcrypt hashes ($2a$/$2b$/$2y$). When *hashed*
    is None (unknown account) a dummy Argon2 verification still runs for timing parity.
    """
    if not hashed:
        _verify_argon2(plain, _DUMMY_HASH)
        return False
    if hashed.startswith("$argon2"):
        return _verify_argon2(plain, hashed)
    if hashed.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
        except ValueError:
            return False
    _verify_argon2(plain, _DUMMY_HASH)
    return False


def password_needs_rehash(hashed: str) -> bool:
    """True for legacy bcrypt hashes or Argon2 hashes made with older parameters."""
    if not hashed.startswith("$argon2"):
        return True
    try:
        return _hasher.check_needs_rehash(hashed)
    except InvalidHashError:
        return True


def _verify_argon2(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


# ─── Opaque tokens (sessions, password reset) ────────────────────────────────

def generate_token() -> tuple[str, str]:
    """Return ``(raw_token, sha256_hex)``. 256 bits of randomness; store only the hash."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_token(raw)


def hash_token(raw: str) -> str:
    """SHA-256 hex digest used to look a token up in the database."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hash_user_agent(user_agent: str | None) -> str:
    """Stable fingerprint of the browser's User-Agent (sessions are bound to it)."""
    return hashlib.sha256((user_agent or "").encode("utf-8")).hexdigest()


# ─── CSRF tokens (synchronizer token derived from the session) ───────────────

# Without a configured secret a random per-process key is used: CSRF tokens then
# change when the server restarts and the frontend fetches a new one from /auth/session.
_CSRF_KEY = (settings.SESSION_SECRET or secrets.token_urlsafe(32)).encode("utf-8")


def csrf_token_for(raw_session_token: str) -> str:
    """CSRF token bound to one session: HMAC-SHA256(server key, session token)."""
    return hmac.new(_CSRF_KEY, raw_session_token.encode("utf-8"), hashlib.sha256).hexdigest()


def csrf_token_valid(raw_session_token: str, presented: str | None) -> bool:
    """Constant-time check of the X-CSRF-Token header against the session's token."""
    if not presented:
        return False
    return hmac.compare_digest(csrf_token_for(raw_session_token), presented)
