"""
ProfileRepository — SQL for the saved farmer profile (one row per account).

Every function takes the account's integer PK, which the service obtains from
the authenticated session — never from request input — so one farmer can only
ever read or change their own row.

Database errors are raised (not swallowed): a failed save must not look like success.
"""

from __future__ import annotations

from typing import Any, Optional

from psycopg import errors as pg_errors, sql
from psycopg.rows import dict_row

from app.database.connection import get_db_connection
from app.models.db.farmer_auth import FarmerProfileRow, FarmerRow

# Columns a profile save may write (whitelist: column names are never taken from input).
PROFILE_COLUMNS = (
    "state", "district", "land_size_value", "land_unit", "land_size_acres", "primary_crop",
    "other_crops", "farming_type", "occupation", "age", "gender", "category", "income_range",
    "residence", "consent_given", "consent_given_at",
)


class VersionConflict(Exception):
    """The profile changed since the client loaded it (or was created concurrently)."""


async def get_farmer_by_farmer_id(farmer_id: str) -> Optional[FarmerRow]:
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM farmers WHERE farmer_id = %s", (farmer_id,))
            row = await cur.fetchone()
    return FarmerRow(**row) if row else None


async def get_profile(farmer_pk: int) -> Optional[FarmerProfileRow]:
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM farmer_profiles WHERE farmer_id = %s", (farmer_pk,))
            row = await cur.fetchone()
    return FarmerProfileRow(**row) if row else None


def _adapt(value: Any) -> Any:
    from psycopg.types.json import Jsonb
    return Jsonb(value) if isinstance(value, list) else value


async def save_profile(farmer_pk: int, changes: dict[str, Any],
                       expected_version: Optional[int]) -> FarmerProfileRow:
    """
    Apply *changes* (None = set to unknown) to the farmer's profile, creating it if needed.

    With *expected_version*, the update only succeeds if the stored version still
    matches (optimistic locking); otherwise VersionConflict. Each save bumps version.
    """
    cols = [c for c in changes if c in PROFILE_COLUMNS]
    if len(cols) != len(changes):
        raise ValueError(f"unknown profile columns: {set(changes) - set(cols)}")
    values = [_adapt(changes[c]) for c in cols]

    # get_db_connection() re-raises anything thrown inside it as DatabaseError, so a
    # conflict is recorded here and raised after the connection block has closed.
    row, conflict = None, False
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT version FROM farmer_profiles WHERE farmer_id = %s FOR UPDATE",
                                  (farmer_pk,))
                current = await cur.fetchone()
                if current is None:
                    if expected_version not in (None, 0):
                        conflict = True
                    else:
                        insert = sql.SQL("INSERT INTO farmer_profiles ({}) VALUES ({}) RETURNING *").format(
                            sql.SQL(", ").join(map(sql.Identifier, ["farmer_id", *cols])),
                            sql.SQL(", ").join(sql.Placeholder() * (len(cols) + 1)))
                        try:
                            async with conn.transaction():          # savepoint
                                await cur.execute(insert, (farmer_pk, *values))
                                row = await cur.fetchone()
                        except pg_errors.UniqueViolation:          # created concurrently
                            conflict = True
                elif expected_version is not None and expected_version != current["version"]:
                    conflict = True
                else:
                    assignments = [sql.SQL("{} = {}").format(sql.Identifier(c), sql.Placeholder())
                                   for c in cols]
                    assignments += [sql.SQL("version = version + 1"), sql.SQL("updated_at = NOW()")]
                    update = sql.SQL("UPDATE farmer_profiles SET {} WHERE farmer_id = {} RETURNING *").format(
                        sql.SQL(", ").join(assignments), sql.Placeholder())
                    await cur.execute(update, (*values, farmer_pk))
                    row = await cur.fetchone()
    if conflict:
        raise VersionConflict()
    return FarmerProfileRow(**row)
