"""
AuthRepository — SQL for account security: sessions, single-use tokens and lockout.

Unlike the read helpers in farmer_repository, these functions do NOT swallow
database errors: a failure to revoke a session or consume a token must surface
(the API turns it into a 503) instead of silently looking like success.

All SQL is parameterized. Only token *hashes* are ever stored or queried.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from psycopg import errors as pg_errors
from psycopg.rows import dict_row

from app.database.connection import get_db_connection
from app.models.db.farmer_auth import AuthSessionRow, FarmerRow

PURPOSE_RESET_PASSWORD = "reset_password"


# ─── Accounts ────────────────────────────────────────────────────────────────

async def get_farmer_by_email(email: str) -> Optional[FarmerRow]:
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM farmers WHERE email = %s", (email.lower(),))
            row = await cur.fetchone()
    return FarmerRow(**row) if row else None


async def get_farmer_by_pk(pk: int) -> Optional[FarmerRow]:
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM farmers WHERE id = %s", (pk,))
            row = await cur.fetchone()
    return FarmerRow(**row) if row else None


async def create_farmer(email: str, password_hash: str, full_name: Optional[str],
                        phone: Optional[str]) -> Optional[FarmerRow]:
    """Insert an account ready to sign in. Returns None if the e-mail or phone is already taken."""
    async with get_db_connection() as conn:
        # Caught here, inside the connection block: get_db_connection() would otherwise
        # re-raise it as a generic DatabaseError (500), revealing that the e-mail exists.
        try:
            async with conn.transaction():
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        """
                        INSERT INTO farmers (farmer_id, email, password_hash, full_name, phone,
                                             password_changed_at)
                        VALUES (%s, %s, %s, %s, %s, NOW())
                        RETURNING *
                        """,
                        (str(uuid.uuid4()), email.lower(), password_hash, full_name, phone),
                    )
                    row = await cur.fetchone()
        except pg_errors.UniqueViolation:
            return None
    return FarmerRow(**row) if row else None


async def record_login_failure(pk: int, max_failures: int, lock_minutes: int) -> None:
    """Count a failed login; lock the account for *lock_minutes* after *max_failures*."""
    async with get_db_connection() as conn:
        await conn.execute(
            """
            UPDATE farmers SET
              locked_until = CASE WHEN failed_login_count + 1 >= %(max)s
                                  THEN NOW() + make_interval(mins => %(mins)s) ELSE locked_until END,
              failed_login_count = CASE WHEN failed_login_count + 1 >= %(max)s
                                        THEN 0 ELSE failed_login_count + 1 END,
              updated_at = NOW()
            WHERE id = %(pk)s
            """,
            {"max": max_failures, "mins": lock_minutes, "pk": pk},
        )


async def record_login_success(pk: int, new_password_hash: Optional[str] = None) -> None:
    """Reset lockout counters, record the login, optionally store an upgraded hash."""
    async with get_db_connection() as conn:
        await conn.execute(
            """
            UPDATE farmers SET failed_login_count = 0, locked_until = NULL,
                   last_login_at = NOW(), login_count = login_count + 1,
                   password_hash = COALESCE(%s, password_hash), updated_at = NOW()
            WHERE id = %s
            """,
            (new_password_hash, pk),
        )


# ─── Sessions ────────────────────────────────────────────────────────────────

async def create_session(pk: int, session_hash: str, user_agent_hash: str,
                         ip_address: Optional[str], expires_at: datetime) -> None:
    async with get_db_connection() as conn:
        await conn.execute(
            """
            INSERT INTO auth_sessions (farmer_id, session_hash, user_agent_hash, ip_address, expires_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (pk, session_hash, user_agent_hash, ip_address, expires_at),
        )


async def get_live_session(session_hash: str) -> Optional[tuple[AuthSessionRow, FarmerRow]]:
    """The session and its account, if not revoked and not past its absolute expiry."""
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT s.id AS s_id, s.farmer_id AS s_farmer_id, s.session_hash, s.user_agent_hash,
                       s.ip_address AS s_ip, s.created_at AS s_created_at, s.last_seen_at,
                       s.expires_at AS s_expires_at, s.revoked_at, s.revoked_reason, s.reauthenticated_at, f.*
                FROM auth_sessions s JOIN farmers f ON f.id = s.farmer_id
                WHERE s.session_hash = %s AND s.revoked_at IS NULL AND s.expires_at > NOW()
                """,
                (session_hash,),
            )
            row = await cur.fetchone()
    if not row:
        return None
    session = AuthSessionRow(
        id=row["s_id"], farmer_id=row["s_farmer_id"], session_hash=row["session_hash"],
        user_agent_hash=row["user_agent_hash"], ip_address=row["s_ip"],
        created_at=row["s_created_at"], last_seen_at=row["last_seen_at"],
        expires_at=row["s_expires_at"], revoked_at=row["revoked_at"],
        revoked_reason=row["revoked_reason"], reauthenticated_at=row.get("reauthenticated_at"),
    )
    return session, FarmerRow(**{k: v for k, v in row.items() if k in FarmerRow.model_fields})


async def touch_session(session_id: int) -> None:
    """Record activity (called at most about once a minute per session)."""
    async with get_db_connection() as conn:
        await conn.execute("UPDATE auth_sessions SET last_seen_at = NOW() WHERE id = %s", (session_id,))


async def mark_reauthenticated(session_id: int) -> None:
    """The password was re-entered in this session (docs/HUMAN_REVIEW.md, Access policy)."""
    async with get_db_connection() as conn:
        await conn.execute("UPDATE auth_sessions SET reauthenticated_at = NOW() WHERE id = %s", (session_id,))


async def revoke_session(session_hash: str, reason: str) -> None:
    async with get_db_connection() as conn:
        await conn.execute(
            "UPDATE auth_sessions SET revoked_at = NOW(), revoked_reason = %s "
            "WHERE session_hash = %s AND revoked_at IS NULL",
            (reason, session_hash),
        )


async def revoke_all_sessions(pk: int, reason: str, except_session_id: Optional[int] = None) -> int:
    async with get_db_connection() as conn:
        cur = await conn.execute(
            "UPDATE auth_sessions SET revoked_at = NOW(), revoked_reason = %s "
            "WHERE farmer_id = %s AND revoked_at IS NULL AND id IS DISTINCT FROM %s",
            (reason, pk, except_session_id),
        )
        return cur.rowcount


# ─── Single-use password-reset tokens ────────────────────────────────────────

async def create_token(pk: int, purpose: str, token_hash: str, expires_at: datetime) -> None:
    """Store a new token; any earlier unused token for the same purpose stops working."""
    async with get_db_connection() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE auth_tokens SET used_at = NOW() "
                "WHERE farmer_id = %s AND purpose = %s AND used_at IS NULL",
                (pk, purpose),
            )
            await conn.execute(
                "INSERT INTO auth_tokens (farmer_id, purpose, token_hash, expires_at) "
                "VALUES (%s, %s, %s, %s)",
                (pk, purpose, token_hash, expires_at),
            )


async def _consume(conn, token_hash: str, purpose: str) -> Optional[int]:
    """Atomically mark a valid token used; returns the account PK, or None."""
    cur = await conn.execute(
        """
        UPDATE auth_tokens SET used_at = NOW()
        WHERE token_hash = %s AND purpose = %s AND used_at IS NULL AND expires_at > NOW()
        RETURNING farmer_id
        """,
        (token_hash, purpose),
    )
    row = await cur.fetchone()
    return row[0] if row else None


async def reset_password_with_token(token_hash: str, new_password_hash: str) -> Optional[int]:
    """
    One transaction: consume the reset token, set the new password, clear the lockout,
    and revoke every session.
    """
    async with get_db_connection() as conn:
        async with conn.transaction():
            pk = await _consume(conn, token_hash, PURPOSE_RESET_PASSWORD)
            if pk is None:
                return None
            await conn.execute(
                """
                UPDATE farmers SET password_hash = %s, password_changed_at = NOW(),
                       failed_login_count = 0, locked_until = NULL, updated_at = NOW()
                WHERE id = %s
                """,
                (new_password_hash, pk),
            )
            await conn.execute(
                "UPDATE auth_sessions SET revoked_at = NOW(), revoked_reason = 'password_reset' "
                "WHERE farmer_id = %s AND revoked_at IS NULL",
                (pk,),
            )
    return pk


async def change_password(pk: int, new_password_hash: str) -> None:
    """Set a new password and revoke every session of the account (the caller issues a new one)."""
    async with get_db_connection() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE farmers SET password_hash = %s, password_changed_at = NOW(), "
                "updated_at = NOW() WHERE id = %s",
                (new_password_hash, pk),
            )
            await conn.execute(
                "UPDATE auth_sessions SET revoked_at = NOW(), revoked_reason = 'password_changed' "
                "WHERE farmer_id = %s AND revoked_at IS NULL",
                (pk,),
            )
