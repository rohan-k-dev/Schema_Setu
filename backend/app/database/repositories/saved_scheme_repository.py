"""
SavedSchemeRepository — SQL for bookmarked schemes and their application checklists
(docs/SAVED_SCHEMES.md).

Every function takes the account's integer PK, which the service obtains from the
authenticated session — never from request input — and every statement is filtered
by it, so a farmer can only read or change their own saved schemes and items. The
database also enforces it: a checklist item's (saved_scheme_id, farmer_id) must match
its saved scheme (composite foreign key, migration 0005).

Database errors are raised, not swallowed: a failed save must not look like success.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Tuple

from psycopg import sql
from psycopg.rows import dict_row

from app.database.connection import get_db_connection
from app.models.db import ApplicationStepRow, SchemeDocumentRow, SchemeRow
from app.models.db.farmer_auth import ChecklistItemRow, SavedSchemeRow

MAX_USER_MILESTONES = 20

# Columns an update may write (whitelists: column names are never taken from input).
SAVED_EDITABLE = ("notes", "application_reference", "scheme_update_seen")
ITEM_EDITABLE = ("completed", "note")


@dataclass(frozen=True)
class ItemSpec:
    """A checklist item derived from the scheme data (source SCHEME)."""
    key: str
    category: str
    label: str
    detail: Optional[str]
    position: int


class MilestoneLimit(Exception):
    """The farmer already has MAX_USER_MILESTONES milestones for this scheme."""


_INSERT_ITEM = (
    "INSERT INTO saved_scheme_checklist_items "
    "(saved_scheme_id, farmer_id, item_key, category, source, label, detail, position, introduced_in_version) "
    "VALUES (%s, %s, %s, %s, 'SCHEME', %s, %s, %s, %s)"
)

_ITEM_OF_OWNER = (
    "SELECT i.* FROM saved_scheme_checklist_items i "
    "JOIN saved_schemes s ON s.id = i.saved_scheme_id AND s.farmer_id = i.farmer_id "
    "WHERE s.farmer_id = %s AND s.scheme_id = %s AND i.id = %s"
)


@dataclass
class SchemeContent:
    """The parts of a scheme its checklist is built from."""
    scheme: SchemeRow
    documents: List[SchemeDocumentRow]
    steps: List[ApplicationStepRow]


async def load_scheme_content(scheme_ids: Sequence[str]) -> dict[str, SchemeContent]:
    """
    Schemes (any status) with their documents and application steps; ids that don't
    exist are left out. Unlike the read helpers in base.py this raises on database
    errors — an outage must never look like "the scheme has no documents", which
    would mark every saved document item as removed.
    """
    if not scheme_ids:
        return {}
    ids = list(scheme_ids)
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM schemes WHERE scheme_id = ANY(%s)", (ids,))
            out = {r["scheme_id"]: SchemeContent(SchemeRow(**r), [], []) for r in await cur.fetchall()}
            await cur.execute("SELECT s.scheme_id AS sid, d.* FROM scheme_documents d "
                              "JOIN schemes s ON s.id = d.scheme_id WHERE s.scheme_id = ANY(%s) "
                              "ORDER BY d.document_order, d.name", (ids,))
            for r in await cur.fetchall():
                out[r.pop("sid")].documents.append(SchemeDocumentRow(**r))
            await cur.execute("SELECT s.scheme_id AS sid, a.* FROM application_steps a "
                              "JOIN schemes s ON s.id = a.scheme_id WHERE s.scheme_id = ANY(%s) "
                              "ORDER BY a.step_number", (ids,))
            for r in await cur.fetchall():
                out[r.pop("sid")].steps.append(ApplicationStepRow(**r))
    return out


async def list_saved(farmer_pk: int) -> List[SavedSchemeRow]:
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM saved_schemes WHERE farmer_id = %s "
                              "ORDER BY saved_at DESC, id DESC", (farmer_pk,))
            rows = await cur.fetchall()
    return [SavedSchemeRow(**r) for r in rows]


async def get_saved(farmer_pk: int, scheme_id: str) -> Optional[SavedSchemeRow]:
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM saved_schemes WHERE farmer_id = %s AND scheme_id = %s",
                              (farmer_pk, scheme_id))
            row = await cur.fetchone()
    return SavedSchemeRow(**row) if row else None


async def list_items(farmer_pk: int, saved_ids: Sequence[int]) -> List[ChecklistItemRow]:
    """Checklist items of the given saved schemes (only the farmer's own)."""
    if not saved_ids:
        return []
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT * FROM saved_scheme_checklist_items WHERE farmer_id = %s "
                "AND saved_scheme_id = ANY(%s) ORDER BY saved_scheme_id, position, id",
                (farmer_pk, list(saved_ids)))
            rows = await cur.fetchall()
    return [ChecklistItemRow(**r) for r in rows]


async def create_saved(
    farmer_pk: int,
    scheme_id: str,
    scheme_name: str,
    eligibility_status: Optional[str],
    notes: Optional[str],
    version: str,
    data_version: Optional[str],
    items: Sequence[ItemSpec],
) -> Tuple[SavedSchemeRow, bool]:
    """
    Save a scheme with its checklist, in one transaction. Returns (row, created).

    Saving a scheme that is already saved (a double click, two tabs) changes nothing
    and returns the existing row with created=False — notes and progress are kept.
    """
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "INSERT INTO saved_schemes (farmer_id, scheme_id, scheme_name, eligibility_status, notes, "
                    "scheme_version, saved_scheme_version, scheme_data_version) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (farmer_id, scheme_id) DO NOTHING RETURNING *",
                    (farmer_pk, scheme_id, scheme_name, eligibility_status, notes, version, version, data_version))
                row = await cur.fetchone()
                if row is None:
                    await cur.execute("SELECT * FROM saved_schemes WHERE farmer_id = %s AND scheme_id = %s",
                                      (farmer_pk, scheme_id))
                    return SavedSchemeRow(**(await cur.fetchone())), False
                await cur.executemany(_INSERT_ITEM, [
                    (row["id"], farmer_pk, s.key, s.category, s.label, s.detail, s.position, version)
                    for s in items])
    return SavedSchemeRow(**row), True


async def sync_scheme_items(
    farmer_pk: int,
    saved_id: int,
    expected_version: Optional[str],
    new_version: str,
    data_version: Optional[str],
    scheme_name: str,
    items: Sequence[ItemSpec],
) -> bool:
    """
    Bring a saved scheme's checklist up to the scheme's current version.

    - Items still in the scheme keep their progress (label / detail / order are refreshed).
    - New items are added.
    - Items the scheme no longer lists are kept with removed_in_version set (never deleted,
      so the farmer's record of what they did is not lost).
    The farmer's own milestones are not touched. Returns False when another request
    already synced it (the stored version is no longer expected_version).
    """
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT scheme_version FROM saved_schemes WHERE id = %s AND farmer_id = %s "
                                  "FOR UPDATE", (saved_id, farmer_pk))
                current = await cur.fetchone()
                if current is None or current["scheme_version"] != expected_version:
                    return False
                await cur.execute("SELECT item_key, removed_in_version FROM saved_scheme_checklist_items "
                                  "WHERE saved_scheme_id = %s AND farmer_id = %s AND source = 'SCHEME'",
                                  (saved_id, farmer_pk))
                existing = {r["item_key"]: r for r in await cur.fetchall()}
                wanted = {s.key for s in items}
                for s in items:
                    if s.key in existing:
                        await cur.execute(
                            "UPDATE saved_scheme_checklist_items SET category = %s, label = %s, detail = %s, "
                            "position = %s, removed_in_version = NULL, updated_at = NOW() "
                            "WHERE saved_scheme_id = %s AND farmer_id = %s AND item_key = %s",
                            (s.category, s.label, s.detail, s.position, saved_id, farmer_pk, s.key))
                    else:
                        await cur.execute(_INSERT_ITEM, (saved_id, farmer_pk, s.key, s.category, s.label,
                                                         s.detail, s.position, new_version))
                gone = [k for k, r in existing.items() if k not in wanted and r["removed_in_version"] is None]
                if gone:
                    await cur.execute(
                        "UPDATE saved_scheme_checklist_items SET removed_in_version = %s, updated_at = NOW() "
                        "WHERE saved_scheme_id = %s AND farmer_id = %s AND item_key = ANY(%s)",
                        (new_version, saved_id, farmer_pk, gone))
                first_sync = expected_version is None          # saved before migration 0005
                await cur.execute(
                    "UPDATE saved_schemes SET scheme_version = %s, scheme_data_version = %s, scheme_name = %s, "
                    "saved_scheme_version = COALESCE(saved_scheme_version, %s), "
                    "previous_scheme_version = CASE WHEN %s THEN previous_scheme_version ELSE %s END, "
                    "scheme_changed_at = CASE WHEN %s THEN scheme_changed_at ELSE NOW() END, "
                    "scheme_update_seen = CASE WHEN %s THEN scheme_update_seen ELSE false END, "
                    "updated_at = NOW() WHERE id = %s AND farmer_id = %s",
                    (new_version, data_version, scheme_name, new_version, first_sync, expected_version,
                     first_sync, first_sync, saved_id, farmer_pk))
    return True


async def delete_saved(farmer_pk: int, scheme_id: str) -> bool:
    """Unsave (its checklist goes with it). False if not saved by this farmer."""
    async with get_db_connection() as conn:
        cur = await conn.execute("DELETE FROM saved_schemes WHERE farmer_id = %s AND scheme_id = %s",
                                 (farmer_pk, scheme_id))
        await conn.commit()
        return cur.rowcount > 0


async def update_saved(farmer_pk: int, scheme_id: str, changes: dict[str, Any]) -> Optional[SavedSchemeRow]:
    """Apply *changes* (None = clear) to the farmer's saved scheme; None if not saved."""
    cols = [c for c in changes if c in SAVED_EDITABLE]
    if len(cols) != len(changes):
        raise ValueError(f"unknown saved-scheme columns: {set(changes) - set(cols)}")
    assignments = [sql.SQL("{} = {}").format(sql.Identifier(c), sql.Placeholder()) for c in cols]
    if "application_reference" in cols:
        assignments.append(sql.SQL("application_reference_updated_at = NOW()"))
    assignments.append(sql.SQL("updated_at = NOW()"))
    query = sql.SQL("UPDATE saved_schemes SET {} WHERE farmer_id = %s AND scheme_id = %s RETURNING *").format(
        sql.SQL(", ").join(assignments))
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query, (*[changes[c] for c in cols], farmer_pk, scheme_id))
            row = await cur.fetchone()
        await conn.commit()
    return SavedSchemeRow(**row) if row else None


async def update_item(farmer_pk: int, scheme_id: str, item_id: int,
                      changes: dict[str, Any]) -> Optional[ChecklistItemRow]:
    """
    Mark an item complete / incomplete and/or set its note. None if the item doesn't
    exist or isn't in this farmer's saved scheme *scheme_id*.
    completed_at is set when an item becomes complete and cleared when it is reopened.
    """
    cols = [c for c in changes if c in ITEM_EDITABLE]
    if len(cols) != len(changes):
        raise ValueError(f"unknown checklist columns: {set(changes) - set(cols)}")
    assignments = [sql.SQL("{} = {}").format(sql.Identifier(c), sql.Placeholder()) for c in cols]
    params: list[Any] = [changes[c] for c in cols]
    if "completed" in cols:
        assignments.append(sql.SQL("completed_at = CASE WHEN %s THEN COALESCE(i.completed_at, NOW()) END"))
        params.append(changes["completed"])
    assignments.append(sql.SQL("updated_at = NOW()"))
    query = sql.SQL(
        "UPDATE saved_scheme_checklist_items i SET {} FROM saved_schemes s "
        "WHERE i.id = %s AND s.id = i.saved_scheme_id AND s.farmer_id = i.farmer_id "
        "AND s.farmer_id = %s AND s.scheme_id = %s RETURNING i.*").format(sql.SQL(", ").join(assignments))
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query, (*params, item_id, farmer_pk, scheme_id))
            row = await cur.fetchone()
        await conn.commit()
    return ChecklistItemRow(**row) if row else None


async def add_milestone(farmer_pk: int, scheme_id: str, key: str, label: str, note: Optional[str],
                        completed: bool) -> Optional[ChecklistItemRow]:
    """
    Add one of the farmer's own milestones (source USER). None if the scheme isn't
    saved by this farmer; MilestoneLimit if they already have MAX_USER_MILESTONES.
    """
    row, limit = None, False
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT id FROM saved_schemes WHERE farmer_id = %s AND scheme_id = %s "
                                  "FOR UPDATE", (farmer_pk, scheme_id))
                saved = await cur.fetchone()
                if saved is None:
                    return None
                await cur.execute("SELECT count(*) AS n, COALESCE(max(position), 0) AS last "
                                  "FROM saved_scheme_checklist_items WHERE saved_scheme_id = %s "
                                  "AND farmer_id = %s AND source = 'USER'", (saved["id"], farmer_pk))
                stats = await cur.fetchone()
                if stats["n"] >= MAX_USER_MILESTONES:
                    limit = True
                else:
                    await cur.execute(
                        "INSERT INTO saved_scheme_checklist_items (saved_scheme_id, farmer_id, item_key, "
                        "category, source, label, note, position, completed, completed_at) "
                        "VALUES (%s, %s, %s, 'MILESTONE', 'USER', %s, %s, %s, %s, "
                        "CASE WHEN %s THEN NOW() END) RETURNING *",
                        (saved["id"], farmer_pk, key, label, note, max(stats["last"], 9000) + 1,
                         completed, completed))
                    row = await cur.fetchone()
    if limit:
        raise MilestoneLimit()
    return ChecklistItemRow(**row)


async def get_item(farmer_pk: int, scheme_id: str, item_id: int) -> Optional[ChecklistItemRow]:
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_ITEM_OF_OWNER, (farmer_pk, scheme_id, item_id))
            row = await cur.fetchone()
    return ChecklistItemRow(**row) if row else None


async def delete_milestone(farmer_pk: int, scheme_id: str, item_id: int) -> bool:
    """Delete one of the farmer's own milestones. Scheme items are never deleted here."""
    async with get_db_connection() as conn:
        cur = await conn.execute(
            "DELETE FROM saved_scheme_checklist_items i USING saved_schemes s "
            "WHERE i.id = %s AND i.source = 'USER' AND s.id = i.saved_scheme_id "
            "AND s.farmer_id = i.farmer_id AND s.farmer_id = %s AND s.scheme_id = %s",
            (item_id, farmer_pk, scheme_id))
        await conn.commit()
        return cur.rowcount > 0
