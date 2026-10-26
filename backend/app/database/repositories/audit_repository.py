"""
AuditRepository — the append-only, hash-chained audit log (``audit_events``,
migrations 0006 + 0007; docs/RBAC.md, docs/ADMIN_OPERATIONS.md).

Only INSERT and SELECT exist here; the database rejects UPDATE and DELETE (trigger).
Each event records actor, action, affected record, timestamp, outcome and the
request's correlation id, and is chained to the previous one by SHA-256
(app/core/audit_chain.py). Writers take a transaction-level advisory lock so the
chain has one order. ``insert`` takes an open cursor (dict rows) so an administrative
change and its audit event commit together.

Details are sanitised before they are stored (app/core/redaction.py): no passwords,
keys, tokens, contact data or profiles ever reach the log.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core import request_context
from app.core.audit_chain import GENESIS, entry_hash, verify
from app.core.permissions import Principal
from app.core.redaction import sanitize
from app.database.connection import get_db_connection
from app.models.db.farmer_auth import AuditEventRow

OUTCOMES = ("SUCCESS", "FAILURE", "DENIED")
_LOCK_KEY = 734_120_001                      # pg_advisory_xact_lock key for the chain

_INSERT = (
    "INSERT INTO audit_events (id, occurred_at, actor_account_id, actor_label, actor_role, action, "
    "target_type, target_id, details, ip_address, outcome, correlation_id, prev_hash, entry_hash) "
    "VALUES (%(id)s, %(occurred_at)s, %(actor_account_id)s, %(actor_label)s, %(actor_role)s, %(action)s, "
    "%(target_type)s, %(target_id)s, %(details_db)s, %(ip_address)s, %(outcome)s, %(correlation_id)s, "
    "%(prev_hash)s, %(entry_hash)s)"
)


def _event(actor: Principal, action: str, target_type: Optional[str], target_id: Optional[str],
           details: Optional[dict], outcome: str, correlation_id: Optional[str]) -> dict:
    if outcome not in OUTCOMES:
        raise ValueError(f"bad outcome {outcome!r}")
    clean = sanitize(details) if details is not None else None
    return {
        "occurred_at": datetime.now(timezone.utc),
        "actor_account_id": actor.account_pk,
        "actor_label": actor.label[:255],
        "actor_role": actor.role.value if actor.role else None,
        "action": action[:40],
        "target_type": target_type[:30] if target_type else None,
        "target_id": (target_id or "")[:100] or None,
        "details": clean,
        "ip_address": (actor.ip_address or "")[:45] or None,
        "outcome": outcome,
        "correlation_id": (correlation_id or request_context.current() or "")[:64] or None,
    }


async def insert(cur, actor: Principal, action: str, target_type: Optional[str] = None,
                 target_id: Optional[str] = None, details: Optional[dict] = None,
                 outcome: str = "SUCCESS", correlation_id: Optional[str] = None) -> None:
    """Append an event inside the caller's transaction (cursor with dict rows)."""
    e = _event(actor, action, target_type, target_id, details, outcome, correlation_id)
    await cur.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_KEY,))
    await cur.execute("SELECT entry_hash FROM audit_events ORDER BY id DESC LIMIT 1")
    last = await cur.fetchone()
    await cur.execute("SELECT nextval(pg_get_serial_sequence('audit_events', 'id')) AS id")
    e["id"] = (await cur.fetchone())["id"]
    e["prev_hash"] = last["entry_hash"] if last else GENESIS
    e["entry_hash"] = entry_hash(e["prev_hash"], e)
    e["details_db"] = Jsonb(e["details"]) if e["details"] is not None else None
    await cur.execute(_INSERT, e)


async def record(actor: Principal, action: str, target_type: Optional[str] = None,
                 target_id: Optional[str] = None, details: Optional[dict] = None,
                 outcome: str = "SUCCESS", correlation_id: Optional[str] = None) -> None:
    """Append an event in its own transaction."""
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await insert(cur, actor, action, target_type, target_id, details, outcome, correlation_id)


_FILTERS = ("action", "target_type", "target_id", "actor_label", "outcome", "correlation_id")


async def list_page(limit: int, offset: int, action: Optional[str] = None,
                    target_type: Optional[str] = None, target_id: Optional[str] = None,
                    actor: Optional[str] = None, outcome: Optional[str] = None,
                    correlation_id: Optional[str] = None, since: Optional[datetime] = None,
                    until: Optional[datetime] = None) -> Tuple[List[AuditEventRow], int]:
    """Newest first, with optional exact-match filters and a time window."""
    values = dict(zip(_FILTERS, (action, target_type, target_id, actor, outcome, correlation_id)))
    where, params = [], []
    for col in _FILTERS:                          # column names come from the fixed tuple, never input
        if values[col] is not None:
            where.append(f"{col} = %s")
            params.append(values[col])
    if since is not None:
        where.append("occurred_at >= %s")
        params.append(since)
    if until is not None:
        where.append("occurred_at < %s")
        params.append(until)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT count(*) AS n FROM audit_events" + clause, params)
            total = (await cur.fetchone())["n"]
            await cur.execute("SELECT * FROM audit_events" + clause +
                              " ORDER BY occurred_at DESC, id DESC LIMIT %s OFFSET %s",
                              [*params, limit, offset])
            rows = await cur.fetchall()
    return [AuditEventRow(**r) for r in rows], total


async def verify_chain(batch: int = 1000) -> dict:
    """Recompute the whole hash chain in id order (streams in batches)."""
    async def rows():
        last_id = 0
        while True:
            async with get_db_connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute("SELECT * FROM audit_events WHERE id > %s ORDER BY id LIMIT %s",
                                      (last_id, batch))
                    chunk = await cur.fetchall()
            if not chunk:
                return
            for r in chunk:
                yield r
            last_id = chunk[-1]["id"]

    collected = [r async for r in rows()]
    return verify(collected)
