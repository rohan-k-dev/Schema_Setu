"""
FarmerRepository — all DB operations for farmer accounts, profiles,
saved schemes, and search history.

All SQL is parameterized. Repository methods return typed models from
app.models.db.farmer_auth, never raw dicts or tuples.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from psycopg.rows import dict_row

from app.core.logging import get_logger
from app.database.connection import get_db_connection, is_db_available
from app.models.db.farmer_auth import (
    FarmerRow,
    FarmerProfileRow,
    RefreshTokenRow,
    SavedSchemeRow,
    SearchHistoryRow,
)

logger = get_logger(__name__)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


async def _fetchone(conn, query: str, params: tuple) -> Optional[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        return await cur.fetchone()


async def _fetchall(conn, query: str, params: tuple) -> list:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        return await cur.fetchall()


async def _execute(conn, query: str, params: tuple) -> None:
    async with conn.cursor() as cur:
        await cur.execute(query, params)


async def _execute_returning(conn, query: str, params: tuple) -> Optional[dict]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        return await cur.fetchone()


# ─── Account CRUD ─────────────────────────────────────────────────────────────

async def get_farmer_by_email(email: str) -> Optional[FarmerRow]:
    """Return the farmer with the given email, or None."""
    if not is_db_available():
        return None
    try:
        async with get_db_connection() as conn:
            row = await _fetchone(
                conn,
                "SELECT * FROM farmers WHERE email = %s",
                (email.lower(),),
            )
            return FarmerRow(**row) if row else None
    except Exception as exc:
        logger.error(f"get_farmer_by_email failed: {exc}")
        return None


async def get_farmer_by_id(farmer_id: str) -> Optional[FarmerRow]:
    """Return the farmer with the given UUID farmer_id, or None."""
    if not is_db_available():
        return None
    try:
        async with get_db_connection() as conn:
            row = await _fetchone(
                conn,
                "SELECT * FROM farmers WHERE farmer_id = %s",
                (farmer_id,),
            )
            return FarmerRow(**row) if row else None
    except Exception as exc:
        logger.error(f"get_farmer_by_id failed: {exc}")
        return None


async def get_farmer_pk(farmer_id: str) -> Optional[int]:
    """Return the integer PK for the given UUID farmer_id, or None."""
    if not is_db_available():
        return None
    try:
        async with get_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id FROM farmers WHERE farmer_id = %s",
                    (farmer_id,),
                )
                row = await cur.fetchone()
                return row[0] if row else None
    except Exception as exc:
        logger.error(f"get_farmer_pk failed: {exc}")
        return None


async def create_farmer(
    email: str,
    password_hash: str,
    full_name: Optional[str] = None,
    phone: Optional[str] = None,
) -> Optional[FarmerRow]:
    """Insert a new farmer account and return the created row."""
    if not is_db_available():
        return None
    new_uuid = str(uuid.uuid4())
    try:
        async with get_db_connection() as conn:
            row = await _execute_returning(
                conn,
                """
                INSERT INTO farmers (farmer_id, email, password_hash, full_name, phone)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING *
                """,
                (new_uuid, email.lower(), password_hash, full_name, phone),
            )
            await conn.commit()
            return FarmerRow(**row) if row else None
    except Exception as exc:
        logger.error(f"create_farmer failed: {exc}")
        return None


async def update_farmer_last_login(farmer_id: str) -> None:
    """Update last_login_at and increment login_count for the given farmer."""
    if not is_db_available():
        return
    try:
        async with get_db_connection() as conn:
            await _execute(
                conn,
                """
                UPDATE farmers
                SET last_login_at = NOW(), login_count = login_count + 1, updated_at = NOW()
                WHERE farmer_id = %s
                """,
                (farmer_id,),
            )
            await conn.commit()
    except Exception as exc:
        logger.error(f"update_farmer_last_login failed: {exc}")


async def set_password_reset_token(
    farmer_id: str, token_hash: str, expires_at: datetime
) -> None:
    """Persist a password-reset token hash for the given farmer."""
    if not is_db_available():
        return
    try:
        async with get_db_connection() as conn:
            await _execute(
                conn,
                """
                UPDATE farmers
                SET password_reset_token = %s,
                    password_reset_expires_at = %s,
                    updated_at = NOW()
                WHERE farmer_id = %s
                """,
                (token_hash, expires_at, farmer_id),
            )
            await conn.commit()
    except Exception as exc:
        logger.error(f"set_password_reset_token failed: {exc}")


async def get_farmer_by_reset_token(token_hash: str) -> Optional[FarmerRow]:
    """Return a farmer whose reset token matches and has not expired."""
    if not is_db_available():
        return None
    try:
        async with get_db_connection() as conn:
            row = await _fetchone(
                conn,
                """
                SELECT * FROM farmers
                WHERE password_reset_token = %s
                  AND password_reset_expires_at > NOW()
                  AND is_active = true
                """,
                (token_hash,),
            )
            return FarmerRow(**row) if row else None
    except Exception as exc:
        logger.error(f"get_farmer_by_reset_token failed: {exc}")
        return None


async def update_password(farmer_id: str, new_hash: str) -> None:
    """Update the password hash and clear the reset token."""
    if not is_db_available():
        return
    try:
        async with get_db_connection() as conn:
            await _execute(
                conn,
                """
                UPDATE farmers
                SET password_hash = %s,
                    password_reset_token = NULL,
                    password_reset_expires_at = NULL,
                    updated_at = NOW()
                WHERE farmer_id = %s
                """,
                (new_hash, farmer_id),
            )
            await conn.commit()
    except Exception as exc:
        logger.error(f"update_password failed: {exc}")


# ─── Refresh tokens ───────────────────────────────────────────────────────────

async def create_refresh_token(
    farmer_pk: int,
    token_hash: str,
    expires_at: datetime,
    user_agent: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> None:
    """Persist a new refresh token."""
    if not is_db_available():
        return
    try:
        async with get_db_connection() as conn:
            await _execute(
                conn,
                """
                INSERT INTO refresh_tokens
                    (farmer_id, token_hash, expires_at, user_agent, ip_address)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (farmer_pk, token_hash, expires_at, user_agent, ip_address),
            )
            await conn.commit()
    except Exception as exc:
        logger.error(f"create_refresh_token failed: {exc}")


async def get_refresh_token(token_hash: str) -> Optional[RefreshTokenRow]:
    """Return a non-revoked, non-expired refresh token row."""
    if not is_db_available():
        return None
    try:
        async with get_db_connection() as conn:
            row = await _fetchone(
                conn,
                """
                SELECT * FROM refresh_tokens
                WHERE token_hash = %s
                  AND revoked = false
                  AND expires_at > NOW()
                """,
                (token_hash,),
            )
            return RefreshTokenRow(**row) if row else None
    except Exception as exc:
        logger.error(f"get_refresh_token failed: {exc}")
        return None


async def revoke_refresh_token(token_hash: str) -> None:
    """Mark a refresh token as revoked."""
    if not is_db_available():
        return
    try:
        async with get_db_connection() as conn:
            await _execute(
                conn,
                """
                UPDATE refresh_tokens
                SET revoked = true, revoked_at = NOW()
                WHERE token_hash = %s
                """,
                (token_hash,),
            )
            await conn.commit()
    except Exception as exc:
        logger.error(f"revoke_refresh_token failed: {exc}")


async def revoke_all_refresh_tokens(farmer_pk: int) -> None:
    """Revoke all tokens for a farmer (logout from all devices)."""
    if not is_db_available():
        return
    try:
        async with get_db_connection() as conn:
            await _execute(
                conn,
                "UPDATE refresh_tokens SET revoked = true, revoked_at = NOW() WHERE farmer_id = %s",
                (farmer_pk,),
            )
            await conn.commit()
    except Exception as exc:
        logger.error(f"revoke_all_refresh_tokens failed: {exc}")


# ─── Farmer Profile ───────────────────────────────────────────────────────────

async def get_farmer_profile(farmer_pk: int) -> Optional[FarmerProfileRow]:
    """Return the saved profile for the given farmer PK, or None."""
    if not is_db_available():
        return None
    try:
        async with get_db_connection() as conn:
            row = await _fetchone(
                conn,
                "SELECT * FROM farmer_profiles WHERE farmer_id = %s",
                (farmer_pk,),
            )
            return FarmerProfileRow(**row) if row else None
    except Exception as exc:
        logger.error(f"get_farmer_profile failed: {exc}")
        return None


# ─── Saved Schemes ────────────────────────────────────────────────────────────

async def get_saved_schemes(farmer_pk: int) -> List[SavedSchemeRow]:
    """Return all saved schemes for a farmer, newest first."""
    if not is_db_available():
        return []
    try:
        async with get_db_connection() as conn:
            rows = await _fetchall(
                conn,
                "SELECT * FROM saved_schemes WHERE farmer_id = %s ORDER BY saved_at DESC",
                (farmer_pk,),
            )
            return [SavedSchemeRow(**r) for r in rows]
    except Exception as exc:
        logger.error(f"get_saved_schemes failed: {exc}")
        return []


# Saving / unsaving (with checklists): saved_scheme_repository.py


# ─── Search History ───────────────────────────────────────────────────────────

async def add_search_history(
    farmer_pk: int,
    query: str,
    results_count: int = 0,
    language: str = "en",
) -> None:
    """Append a new search history entry (capped at 50 per farmer)."""
    if not is_db_available():
        return
    try:
        async with get_db_connection() as conn:
            await _execute(
                conn,
                """
                INSERT INTO search_history (farmer_id, query, results_count, language)
                VALUES (%s, %s, %s, %s)
                """,
                (farmer_pk, query, results_count, language),
            )
            # Keep only the 50 most recent entries per farmer
            await _execute(
                conn,
                """
                DELETE FROM search_history
                WHERE farmer_id = %s
                  AND id NOT IN (
                      SELECT id FROM search_history
                      WHERE farmer_id = %s
                      ORDER BY searched_at DESC
                      LIMIT 50
                  )
                """,
                (farmer_pk, farmer_pk),
            )
            await conn.commit()
    except Exception as exc:
        logger.error(f"add_search_history failed: {exc}")


async def get_search_history(farmer_pk: int, limit: int = 10) -> List[SearchHistoryRow]:
    """Return the most recent *limit* search queries for a farmer."""
    if not is_db_available():
        return []
    try:
        async with get_db_connection() as conn:
            rows = await _fetchall(
                conn,
                "SELECT * FROM search_history WHERE farmer_id = %s ORDER BY searched_at DESC LIMIT %s",
                (farmer_pk, limit),
            )
            return [SearchHistoryRow(**r) for r in rows]
    except Exception as exc:
        logger.error(f"get_search_history failed: {exc}")
        return []
