"""
SearchHistoryRepository — SQL for a farmer's recent searches (docs/DASHBOARD.md).

Retention policy (enforced here, on every write and read):
  - at most MAX_ENTRIES per farmer (older ones are deleted on insert);
  - nothing older than RETENTION_DAYS (expired rows are deleted on insert and read).

Every function takes the account's integer PK, which the service obtains from the
authenticated session, and every statement is filtered by it — a farmer can only
list or delete their own entries. Database errors are raised, not swallowed.
"""

from __future__ import annotations

from typing import List, Tuple

from psycopg.rows import dict_row

from app.database.connection import get_db_connection
from app.models.db.farmer_auth import SearchHistoryRow

MAX_ENTRIES = 50
RETENTION_DAYS = 90

_PRUNE_EXPIRED = (
    "DELETE FROM search_history WHERE farmer_id = %s "
    "AND searched_at < now() - make_interval(days => %s)"
)


async def add(farmer_pk: int, query: str, results_count: int, language: str) -> None:
    async with get_db_connection() as conn:
        await conn.execute(
            "INSERT INTO search_history (farmer_id, query, results_count, language) "
            "VALUES (%s, %s, %s, %s)",
            (farmer_pk, query, results_count, language),
        )
        await conn.execute(_PRUNE_EXPIRED, (farmer_pk, RETENTION_DAYS))
        await conn.execute(
            """
            DELETE FROM search_history
            WHERE farmer_id = %s
              AND id NOT IN (SELECT id FROM search_history WHERE farmer_id = %s
                             ORDER BY searched_at DESC, id DESC LIMIT %s)
            """,
            (farmer_pk, farmer_pk, MAX_ENTRIES),
        )
        await conn.commit()


async def list_page(farmer_pk: int, limit: int, offset: int) -> Tuple[List[SearchHistoryRow], int]:
    """One page of the farmer's searches (newest first) and the total count."""
    async with get_db_connection() as conn:
        await conn.execute(_PRUNE_EXPIRED, (farmer_pk, RETENTION_DAYS))
        await conn.commit()
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT count(*) AS n FROM search_history WHERE farmer_id = %s", (farmer_pk,))
            total = (await cur.fetchone())["n"]
            await cur.execute(
                "SELECT * FROM search_history WHERE farmer_id = %s "
                "ORDER BY searched_at DESC, id DESC LIMIT %s OFFSET %s",
                (farmer_pk, limit, offset),
            )
            rows = await cur.fetchall()
    return [SearchHistoryRow(**r) for r in rows], total


async def delete_one(farmer_pk: int, entry_id: int) -> bool:
    """Delete one entry; False if it doesn't exist or belongs to another farmer."""
    async with get_db_connection() as conn:
        cur = await conn.execute(
            "DELETE FROM search_history WHERE id = %s AND farmer_id = %s", (entry_id, farmer_pk))
        await conn.commit()
        return cur.rowcount > 0


async def clear(farmer_pk: int) -> int:
    async with get_db_connection() as conn:
        cur = await conn.execute("DELETE FROM search_history WHERE farmer_id = %s", (farmer_pk,))
        await conn.commit()
        return cur.rowcount
