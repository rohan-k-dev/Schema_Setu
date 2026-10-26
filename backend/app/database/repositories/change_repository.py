"""
ChangeRepository — detected scheme changes and their review (docs/SCHEME_UPDATES.md).

A change is created PENDING and only an administrator can move it to APPROVED or
REJECTED; publishing moves APPROVED to PUBLISHED. Re-running detection on the same
data creates no duplicates: the partial unique index on the fingerprint skips a
change that is already pending or approved. Database errors are raised.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.database.connection import get_db_connection


async def _all(q: str, p: tuple = ()) -> List[dict]:
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(q, p)
            return await cur.fetchall()


async def create_batch(batch: Dict[str, Any], changes: List[Dict[str, Any]]) -> Tuple[dict, int, int]:
    """Insert a batch and its changes. Returns (batch, new_changes, duplicates_skipped)."""
    created = 0
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "INSERT INTO scheme_change_batches (id, source_name, source_sha256, base_version, candidate_count, "
                    "invalid_records, warnings, detected_by, correlation_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "RETURNING *",
                    (batch["id"], batch["source_name"], batch["source_sha256"], batch["base_version"],
                     batch["candidate_count"], Jsonb(batch["invalid_records"]), Jsonb(batch["warnings"]),
                     batch["detected_by"], batch["correlation_id"]))
                row = await cur.fetchone()
                for c in changes:
                    await cur.execute(
                        "INSERT INTO scheme_changes (batch_id, scheme_id, scheme_name, category, consequential, summary, "
                        "before, after, fingerprint, provenance) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                        "ON CONFLICT (fingerprint) WHERE status IN ('PENDING', 'APPROVED') DO NOTHING RETURNING id",
                        (batch["id"], c["scheme_id"], c["scheme_name"][:500], c["category"], c["consequential"],
                         c["summary"], Jsonb(c["before"]), Jsonb(c["after"]), c["fingerprint"], Jsonb(c["provenance"])))
                    created += 1 if await cur.fetchone() else 0
    return row, created, len(changes) - created


_BATCH_COUNTS = (
    "SELECT b.*, "
    "count(c.id) FILTER (WHERE c.status = 'PENDING') AS pending, "
    "count(c.id) FILTER (WHERE c.status = 'APPROVED') AS approved, "
    "count(c.id) FILTER (WHERE c.status = 'REJECTED') AS rejected, "
    "count(c.id) FILTER (WHERE c.status = 'PUBLISHED') AS published, "
    "count(c.id) AS total "
    "FROM scheme_change_batches b LEFT JOIN scheme_changes c ON c.batch_id = b.id"
)


async def list_batches(limit: int, offset: int) -> Tuple[List[dict], int]:
    total = (await _all("SELECT count(*) AS n FROM scheme_change_batches"))[0]["n"]
    rows = await _all(_BATCH_COUNTS + " GROUP BY b.id ORDER BY b.detected_at DESC LIMIT %s OFFSET %s", (limit, offset))
    return rows, total


async def get_batch(batch_id: str) -> Optional[dict]:
    rows = await _all(_BATCH_COUNTS + " WHERE b.id = %s GROUP BY b.id", (batch_id,))
    return rows[0] if rows else None


async def list_changes(batch_id: Optional[str], status: Optional[str], limit: int,
                       offset: int) -> Tuple[List[dict], int]:
    where, params = [], []
    if batch_id:
        where.append("batch_id = %s")
        params.append(batch_id)
    if status:
        where.append("status = %s")
        params.append(status)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = (await _all("SELECT count(*) AS n FROM scheme_changes" + clause, tuple(params)))[0]["n"]
    rows = await _all("SELECT * FROM scheme_changes" + clause +
                      " ORDER BY consequential DESC, scheme_id, id LIMIT %s OFFSET %s", (*params, limit, offset))
    return rows, total


async def review(change_id: int, decision: str, reviewer: str, note: Optional[str]) -> Optional[dict]:
    """PENDING → APPROVED / REJECTED in an OPEN batch; None if not reviewable (already decided, closed)."""
    rows = await _write(
        "UPDATE scheme_changes c SET status = %s, reviewed_by = %s, reviewed_at = NOW(), review_note = %s "
        "FROM scheme_change_batches b WHERE c.id = %s AND c.batch_id = b.id AND b.status = 'OPEN' "
        "AND c.status = 'PENDING' RETURNING c.*", (decision, reviewer, note, change_id))
    return rows[0] if rows else None


async def get_change(change_id: int) -> Optional[dict]:
    rows = await _all("SELECT * FROM scheme_changes WHERE id = %s", (change_id,))
    return rows[0] if rows else None


async def discard_batch(batch_id: str) -> bool:
    async with get_db_connection() as conn:
        async with conn.transaction():
            cur = await conn.execute("UPDATE scheme_change_batches SET status = 'DISCARDED' "
                                     "WHERE id = %s AND status = 'OPEN'", (batch_id,))
            if cur.rowcount == 0:
                return False
            await conn.execute("UPDATE scheme_changes SET status = 'DISCARDED' WHERE batch_id = %s "
                               "AND status IN ('PENDING', 'APPROVED')", (batch_id,))
    return True


async def approved_changes(batch_id: str) -> List[dict]:
    return await _all("SELECT * FROM scheme_changes WHERE batch_id = %s AND status = 'APPROVED' ORDER BY id",
                      (batch_id,))


async def mark_published(batch_id: str, version: str) -> List[dict]:
    """OPEN → PUBLISHED; APPROVED changes → PUBLISHED. Returns the published changes ([] if not OPEN)."""
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("UPDATE scheme_change_batches SET status = 'PUBLISHED', published_at = NOW(), "
                                  "published_version = %s WHERE id = %s AND status = 'OPEN' RETURNING id",
                                  (version, batch_id))
                if not await cur.fetchone():
                    return []
                await cur.execute("UPDATE scheme_changes SET status = 'PUBLISHED' WHERE batch_id = %s "
                                  "AND status = 'APPROVED' RETURNING *", (batch_id,))
                return await cur.fetchall()


async def _write(q: str, p: tuple) -> List[dict]:
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(q, p)
            rows = await cur.fetchall()
        await conn.commit()
    return rows
