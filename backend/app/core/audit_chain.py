"""
Tamper evidence for the audit log (docs/ADMIN_OPERATIONS.md).

Every audit event stores ``prev_hash`` (the previous event's hash) and ``entry_hash``,
a SHA-256 over prev_hash + the event's own fields. Changing, deleting or reordering
any stored event breaks the chain from that point, which ``verify`` reports — even
when someone with database rights bypassed the append-only trigger.

Used by app.database.repositories.audit_repository and by migration 0007 (backfill),
so the definition lives in one place. Pure functions, no I/O.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional

GENESIS = "0" * 64

FIELDS = ("id", "occurred_at", "actor_account_id", "actor_label", "actor_role", "action", "target_type",
          "target_id", "details", "ip_address", "outcome", "correlation_id")


def _norm(field: str, value: Any) -> Any:
    if field == "occurred_at" and isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds")
    return value


def entry_hash(prev_hash: str, row: Mapping[str, Any]) -> str:
    payload = {f: _norm(f, row.get(f)) for f in FIELDS}
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(f"{prev_hash}|{blob}".encode()).hexdigest()


def verify(rows: Iterable[Mapping[str, Any]]) -> dict:
    """
    Check a chain given in id order. Returns {"valid", "checked", "first_broken_id", "reason"}.
    A gap in ids is fine (an id taken by a rolled-back transaction); a missing row is not,
    because the next row's prev_hash no longer matches.
    """
    prev = GENESIS
    checked = 0
    for row in rows:
        checked += 1
        reason: Optional[str] = None
        if row.get("prev_hash") != prev:
            reason = "prev_hash does not match the previous event (an event was removed, inserted or reordered)"
        elif row.get("entry_hash") != entry_hash(prev, row):
            reason = "entry_hash does not match the event's contents (the event was modified)"
        if reason:
            return {"valid": False, "checked": checked, "first_broken_id": row.get("id"), "reason": reason}
        prev = row["entry_hash"]
    return {"valid": True, "checked": checked, "first_broken_id": None, "reason": None}
