"""
ReviewRepository — SQL for the human-review queue (migration 0009, docs/HUMAN_REVIEW.md).

Every change is a compare-and-swap on the case's version, written together with its history
event and its audit_events row in ONE transaction. Database errors are raised, not swallowed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core.permissions import Principal
from app.database.connection import get_db_connection
from app.database.repositories import audit_repository

_JSON = ("profile_snapshot", "scheme_ids", "schemes", "eligibility_results", "evidence", "rule_conflicts",
         "source_conflicts", "failed_channels")
# Columns a transition may change (whitelist: names never come from input).
_MUTABLE = ("status", "assignee", "assigned_at", "awaiting_verification", "decision", "data_correction_needed",
            "reviewer_id", "reviewer_action", "reviewer_note", "reviewed_at")
_OPEN = ("PENDING", "IN_REVIEW")


def _out(row: Optional[dict]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    row = dict(row)
    row["farmer_pk"] = row.pop("farmer_id", None)
    return row


async def _event(cur, case_id: str, e: Dict[str, Any]) -> None:
    await cur.execute(
        "INSERT INTO review_case_events (case_id, event, actor, from_status, to_status, note) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (case_id, e["event"], e["actor"], e.get("from_status"), e.get("to_status"), e.get("note")))


async def insert(row: Dict[str, Any], actor: Principal, note: str) -> Tuple[Dict[str, Any], bool]:
    """Create a case, or return the open case for the same (session, reason)."""
    cols = [k for k in row if k != "farmer_pk"]
    values = [Jsonb(row[k]) if k in _JSON else row[k] for k in cols]
    query = sql.SQL("INSERT INTO review_cases ({}) VALUES ({}) ON CONFLICT (session_id, reason) "
                    "WHERE status IN ('PENDING', 'IN_REVIEW') DO NOTHING RETURNING *").format(
        sql.SQL(", ").join(map(sql.Identifier, cols)), sql.SQL(", ").join(sql.Placeholder() * len(cols)))
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(query, values)
                created = await cur.fetchone()
                if created is None:
                    await cur.execute("SELECT * FROM review_cases WHERE session_id = %s AND reason = %s "
                                      "AND status IN ('PENDING', 'IN_REVIEW')", (row["session_id"], row["reason"]))
                    return _out(await cur.fetchone()), False
                await _event(cur, row["case_id"], {"event": "CREATED", "actor": actor.label,
                                                   "to_status": "PENDING", "note": note})
                await audit_repository.insert(cur, actor, "REVIEW_CASE_CREATED", "review_case", row["case_id"],
                                              {"reason": row["reason"], "schemes": row["scheme_ids"][:20]})
                return _out(created), True


async def get(case_id: str) -> Optional[Dict[str, Any]]:
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM review_cases WHERE case_id = %s", (case_id,))
            return _out(await cur.fetchone())


_GRANTED = ("EXISTS (SELECT 1 FROM review_case_grants g WHERE g.case_id = review_cases.case_id "
            "AND g.reviewer_id = %s AND g.revoked_at IS NULL AND g.expires_at > now())")


def _scope(scope) -> Tuple[List[str], list]:
    """WHERE parts limiting a listing to a reviewer's scope (None = all cases)."""
    if scope is None:
        return [], []
    where, params = [], []
    if scope.unlinked_only:
        where.append("farmer_id IS NULL")
    if scope.label is not None:
        where.append("(assignee = %s OR " + _GRANTED + " OR (%s AND status = 'PENDING' AND assignee IS NULL))")
        params += [scope.label, scope.pk if scope.pk is not None else -1, bool(scope.queue)]
    return where, params


async def list_cases(status: Optional[str], reason: Optional[str], assignee: Optional[str],
                     limit: int, offset: int, scope=None) -> Tuple[List[Dict[str, Any]], int]:
    where, params = _scope(scope)
    if status:
        where.append("status = %s")
        params.append(status)
    if reason:
        where.append("reason = %s")
        params.append(reason)
    if assignee == "":
        where.append("assignee IS NULL")
    elif assignee is not None:
        where.append("assignee = %s")
        params.append(assignee)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    order = " ORDER BY created_at ASC, case_id" if status in _OPEN else " ORDER BY created_at DESC, case_id"
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT count(*) AS n FROM review_cases" + clause, params)
            total = (await cur.fetchone())["n"]
            await cur.execute("SELECT * FROM review_cases" + clause + order + " LIMIT %s OFFSET %s",
                              (*params, limit, offset))
            return [_out(r) for r in await cur.fetchall()], total


async def stats(scope=None) -> Dict[str, int]:
    where, params = _scope(scope)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT count(*) AS total, "
                "count(*) FILTER (WHERE status = 'PENDING') AS pending, "
                "count(*) FILTER (WHERE status = 'IN_REVIEW') AS in_review, "
                "count(*) FILTER (WHERE status = 'RESOLVED') AS resolved, "
                "count(*) FILTER (WHERE status = 'DISMISSED') AS dismissed, "
                "count(*) FILTER (WHERE awaiting_verification) AS awaiting_verification "
                "FROM review_cases" + clause, params)
            return dict(await cur.fetchone())


async def apply(case_id: str, expected_version: int, changes: Dict[str, Any], event: Dict[str, Any],
                actor: Principal, audit_action: str, audit_details: dict) -> Optional[Dict[str, Any]]:
    """Apply *changes* only if the case is still at *expected_version*; None if it moved on."""
    cols = [k for k in changes if k in _MUTABLE]
    query = sql.SQL("UPDATE review_cases SET {}, version = version + 1, updated_at = now() "
                    "WHERE case_id = %s AND version = %s RETURNING *").format(
        sql.SQL(", ").join(sql.SQL("{} = %s").format(sql.Identifier(c)) for c in cols))
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(query, [changes[c] for c in cols] + [case_id, expected_version])
                row = await cur.fetchone()
                if row is None:
                    return None
                await _event(cur, case_id, event)
                await audit_repository.insert(cur, actor, audit_action, "review_case", case_id, audit_details)
                return _out(row)


async def add_event(case_id: str, event: Dict[str, Any], actor: Principal, audit_action: str) -> Dict[str, Any]:
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("UPDATE review_cases SET updated_at = now() WHERE case_id = %s", (case_id,))
                await _event(cur, case_id, event)
                await audit_repository.insert(cur, actor, audit_action, "review_case", case_id, {})
                await cur.execute("SELECT * FROM review_case_events WHERE case_id = %s ORDER BY id DESC LIMIT 1",
                                  (case_id,))
                return dict(await cur.fetchone())


async def events(case_id: str) -> List[Dict[str, Any]]:
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM review_case_events WHERE case_id = %s ORDER BY id", (case_id,))
            return [dict(r) for r in await cur.fetchall()]


async def link_farmer(case_id: str, farmer_pk: int) -> None:
    async with get_db_connection() as conn:
        await conn.execute("UPDATE review_cases SET farmer_id = COALESCE(farmer_id, %s) WHERE case_id = %s",
                           (farmer_pk, case_id))
        await conn.commit()


async def for_farmer(farmer_pk: int, limit: int = 50) -> List[Dict[str, Any]]:
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM review_cases WHERE farmer_id = %s ORDER BY created_at DESC LIMIT %s",
                              (farmer_pk, limit))
            return [_out(r) for r in await cur.fetchall()]


# ─── explicit, expiring per-case access grants (migration 0010) ───────────────

async def has_grant(case_id: str, reviewer_pk: int) -> bool:
    async with get_db_connection() as conn:
        cur = await conn.execute(
            "SELECT 1 FROM review_case_grants WHERE case_id = %s AND reviewer_id = %s "
            "AND revoked_at IS NULL AND expires_at > now()", (case_id, reviewer_pk))
        return await cur.fetchone() is not None


async def grant(case_id: str, reviewer_pk: int, by: str, expires_at, actor: Principal,
                details: dict) -> Dict[str, Any]:
    """Replace any earlier grant for the pair (also an expired one) with a new one; audited together."""
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("UPDATE review_case_grants SET revoked_at = now(), revoked_by = %s "
                                  "WHERE case_id = %s AND reviewer_id = %s AND revoked_at IS NULL",
                                  (by, case_id, reviewer_pk))
                await cur.execute("INSERT INTO review_case_grants (case_id, reviewer_id, granted_by, expires_at) "
                                  "VALUES (%s, %s, %s, %s) RETURNING *", (case_id, reviewer_pk, by, expires_at))
                row = dict(await cur.fetchone())
                await audit_repository.insert(cur, actor, "REVIEW_ACCESS_GRANTED", "review_case", case_id, details)
                row["reviewer_pk"] = row.pop("reviewer_id")
                return row


async def revoke_grant(case_id: str, reviewer_pk: int, by: str, actor: Principal, details: dict) -> bool:
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("UPDATE review_case_grants SET revoked_at = now(), revoked_by = %s "
                                  "WHERE case_id = %s AND reviewer_id = %s AND revoked_at IS NULL RETURNING id",
                                  (by, case_id, reviewer_pk))
                if await cur.fetchone() is None:
                    return False
                await audit_repository.insert(cur, actor, "REVIEW_ACCESS_REVOKED", "review_case", case_id, details)
                return True


async def grants(case_id: str) -> List[Dict[str, Any]]:
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM review_case_grants WHERE case_id = %s ORDER BY id", (case_id,))
            out = []
            for r in await cur.fetchall():
                r = dict(r)
                r["reviewer_pk"] = r.pop("reviewer_id")
                out.append(r)
            return out

