"""
LiveSnapshotRepository — provenance of live official-source checks (migration 0011,
docs/LIVE_VERIFICATION.md).

record() keeps the LAST KNOWN-GOOD extraction of every page: a new extraction replaces it only
when it succeeded and lost none of the fields the known-good one had; otherwise the attempt is
stored separately and the known-good one stays. The previous known-good value is kept too, and
the change is classified (NEW / UNCHANGED / UPDATED / INCOMPLETE / UNPARSEABLE / MISSING / FAILED).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.database.connection import get_db_connection

_RANK = {"COMPLETE": 2, "PARTIAL": 1, "EMPTY": 0, None: 0}


def classify(existing: Optional[dict], ok: bool, not_found: bool, quality: str, fields: Dict[str, Any],
             content_hash: str) -> tuple[str, bool]:
    """(change_status, replace_last_good) for a new attempt — the rule that protects known-good data."""
    if not ok:
        return ("MISSING" if not_found else "FAILED"), False
    if quality == "EMPTY":
        return "UNPARSEABLE", False
    if not existing or not existing.get("last_good"):
        return "NEW", True
    if content_hash and content_hash == existing.get("last_good_hash"):
        return "UNCHANGED", True
    lost = set(existing["last_good"]) - set(fields)
    if lost or _RANK.get(quality, 0) < _RANK.get(existing.get("last_good_quality"), 0):
        return "INCOMPLETE", False                     # don't overwrite a valid record with a poorer one
    return "UPDATED", True


async def get(canonical: str) -> Optional[Dict[str, Any]]:
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM live_source_snapshots WHERE canonical_url = %s", (canonical,))
            return await cur.fetchone()


async def record(*, canonical: str, url: str, host: str, category: str, scheme_id: Optional[str], method: str,
                 status: str, http_status: Optional[int], ok: bool, not_found: bool, quality: str,
                 fields: Dict[str, Any], content_hash: str, etag: Optional[str], last_modified: Optional[str],
                 error: Optional[str]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT * FROM live_source_snapshots WHERE canonical_url = %s FOR UPDATE", (canonical,))
                existing = await cur.fetchone()
                change, replace = classify(existing, ok, not_found, quality, fields, content_hash)
                dup = None
                if replace and content_hash:
                    await cur.execute("SELECT canonical_url FROM live_source_snapshots WHERE last_good_hash = %s "
                                      "AND canonical_url <> %s LIMIT 1", (content_hash, canonical))
                    row = await cur.fetchone()
                    dup = row["canonical_url"] if row else None
                values = {
                    "url": url, "host": host, "category": category,
                    "scheme_id": scheme_id or (existing or {}).get("scheme_id"), "method": method,
                    "last_status": status, "http_status": http_status, "last_attempt_at": now,
                    "etag": etag, "last_modified": last_modified, "attempt_extracted": Jsonb(fields or {}),
                    "attempt_quality": quality, "change_status": change, "duplicate_of": dup, "error": error,
                }
                if ok:
                    values["last_success_at"] = now
                if replace:
                    changed = change == "UPDATED"
                    values.update(last_good=Jsonb(fields), last_good_hash=content_hash, last_good_quality=quality,
                                  last_good_at=now)
                    if changed and existing:
                        values.update(previous_good=Jsonb(existing["last_good"]),
                                      previous_good_at=existing["last_good_at"])
                cols = list(values)                                      # fixed names, composed safely
                params = {**values, "canonical_url": canonical}
                if existing:
                    query = sql.SQL("UPDATE live_source_snapshots SET {} WHERE canonical_url = %(canonical_url)s "
                                    "RETURNING *").format(sql.SQL(", ").join(
                                        sql.SQL("{} = {}").format(sql.Identifier(c), sql.Placeholder(c)) for c in cols))
                else:
                    query = sql.SQL("INSERT INTO live_source_snapshots (canonical_url, {}) VALUES "
                                    "(%(canonical_url)s, {}) RETURNING *").format(
                                        sql.SQL(", ").join(map(sql.Identifier, cols)),
                                        sql.SQL(", ").join(map(sql.Placeholder, cols)))
                await cur.execute(query, params)
                return dict(await cur.fetchone())


async def list_recent(change_status: Optional[str], limit: int, offset: int) -> tuple[List[Dict[str, Any]], int]:
    where, params = ("WHERE change_status = %s", [change_status]) if change_status else ("", [])
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT count(*) AS n FROM live_source_snapshots " + where, params)
            total = (await cur.fetchone())["n"]
            await cur.execute("SELECT canonical_url, url, host, category, scheme_id, method, last_status, http_status, "
                              "last_attempt_at, last_success_at, last_good_at, last_good_quality, change_status, "
                              "duplicate_of, error, previous_good_at FROM live_source_snapshots " + where +
                              " ORDER BY last_attempt_at DESC LIMIT %s OFFSET %s", (*params, limit, offset))
            return [dict(r) for r in await cur.fetchall()], total
