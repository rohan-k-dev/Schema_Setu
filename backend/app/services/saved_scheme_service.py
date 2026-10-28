"""
Saved schemes with an application checklist per scheme (docs/SAVED_SCHEMES.md).

- Only schemes in SchemeSetu's database can be saved; name and version come from the
  database, never from the client.
- The checklist is built from the scheme's own data: required documents, preparation,
  the official application steps, submission and acknowledgement. The farmer can add
  their own later milestones.
- Each saved scheme records the scheme VERSION (a content hash of the parts the
  checklist uses). When the scheme data changes, the checklist is brought up to date on
  the next read: progress on unchanged items is kept, new items are added, and items the
  scheme no longer lists are kept but marked as no longer current. The farmer sees a
  notice until they acknowledge it.
- Progress is USER-REPORTED. SchemeSetu is not connected to any government
  application-tracking system; nothing here means a department confirmed a step.

Every operation is keyed by the authenticated farmer_id (from the session), resolved to
the account PK here; requests can never name another account.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Dict, List, Optional, Sequence

from app.database.repositories import profile_repository as profile_repo
from app.database.repositories import saved_scheme_repository as repo
from app.database.repositories.saved_scheme_repository import ItemSpec, SchemeContent
from app.models.auth_schemas import SaveSchemeRequest
from app.models.db.farmer_auth import ChecklistItemRow, SavedSchemeRow
from app.models.saved_scheme_schemas import (
    ChecklistItem,
    ChecklistItemUpdateRequest,
    MilestoneCreateRequest,
    ProgressSummary,
    SavedSchemeDetail,
    SavedSchemeSummary,
    SavedSchemeUpdateRequest,
    SaveSchemeResult,
    SchemeUpdateNotice,
)

SHORT_VERSION = 12            # characters of the version hash shown to clients

SUBMIT_KEY = "submit:application"
ACK_KEY = "ack:received"

_CATEGORY_BASE = {"DOCUMENT": 100, "PREPARATION": 200, "APPLICATION": 300,
                  "SUBMISSION": 400, "ACKNOWLEDGEMENT": 500}

_MODE_TEXT = {"ONLINE": "Online", "OFFLINE": "In person", "CSC": "At a Common Service Centre (CSC)",
              "OFFICE": "At the office", "HYBRID": "Online or in person"}


class SavedSchemeError(Exception):
    """Raised for saved-scheme errors; ``code`` maps to the HTTP status in the API."""

    def __init__(self, message: str, code: str):
        self.message = message
        self.code = code
        super().__init__(message)


# ─── Version and checklist (pure functions) ──────────────────────────────────

def scheme_version(c: SchemeContent) -> str:
    """Content hash of everything the checklist is built from (stable across re-imports)."""
    s = c.scheme
    material = {
        "scheme_id": s.scheme_id, "name": s.name, "data_version": s.data_version,
        "official_url": s.official_url, "application_url": s.application_url,
        "documents": [[d.name, d.mandatory, d.description] for d in c.documents],
        "steps": [[a.step_number, a.description, a.mode, a.portal_name, a.portal_url, a.office_name, a.notes]
                  for a in c.steps],
    }
    blob = json.dumps(material, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def _key(prefix: str, text: str) -> str:
    """Item key from the item's meaning, not its database id (ids change on every import)."""
    norm = " ".join(text.lower().split())
    return f"{prefix}:{hashlib.sha256(norm.encode()).hexdigest()[:16]}"


def build_checklist(c: SchemeContent) -> List[ItemSpec]:
    s = c.scheme
    out: List[ItemSpec] = []

    def add(key, category, label, detail=None):
        if any(i.key == key for i in out):
            return
        n = sum(1 for i in out if i.category == category)
        out.append(ItemSpec(key, category, label[:300], detail, _CATEGORY_BASE[category] + n))

    for d in c.documents:
        need = "Required" if d.mandatory else "Needed in some cases"
        add(_key("doc", d.name), "DOCUMENT", d.name, f"{need}. {d.description}" if d.description else need)
    if not c.documents:
        add("doc:official-list", "DOCUMENT", "Find out which documents are needed",
            "SchemeSetu doesn't have this scheme's document list yet. Check the official website "
            "or ask at the office.")

    where = f" ({s.official_url})" if s.official_url else ""
    add("prep:eligibility", "PREPARATION", "Read the official eligibility conditions",
        f"On the scheme's official website{where}.")
    add("prep:copies", "PREPARATION", "Keep the originals and photocopies of your documents together")

    for a in c.steps:
        detail = " · ".join(x for x in (_MODE_TEXT.get(a.mode or ""), a.portal_name, a.office_name, a.notes) if x)
        add(_key("step", a.description), "APPLICATION", a.description, detail or None)
    if not c.steps:
        add("app:find-process", "APPLICATION", "Find out how to apply",
            "Check the official website, or ask at your nearest CSC or agriculture office.")

    add(SUBMIT_KEY, "SUBMISSION", "Submit your application",
        f"Apply online: {s.application_url}" if s.application_url
        else "At the portal or office given in the application steps.")
    add(ACK_KEY, "ACKNOWLEDGEMENT", "Get an acknowledgement or application number",
        "Keep the receipt or SMS. You can note the number on this page if you want to.")
    return out


def _stage(items: Sequence[ChecklistItemRow]) -> str:
    done = {i.item_key for i in items if i.completed and i.removed_in_version is None}
    if ACK_KEY in done:
        return "ACKNOWLEDGED"
    if SUBMIT_KEY in done:
        return "SUBMITTED"
    return "PREPARING" if done or any(i.completed for i in items) else "NOT_STARTED"


def _short(v: Optional[str]) -> Optional[str]:
    return v[:SHORT_VERSION] if v else None


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


def _item(i: ChecklistItemRow, row: SavedSchemeRow) -> ChecklistItem:
    return ChecklistItem(
        id=i.id, key=i.item_key, category=i.category, source=i.source, label=i.label, detail=i.detail,
        completed=i.completed, completed_at=_iso(i.completed_at), note=i.note,
        current=i.removed_in_version is None,
        added_in_update=bool(row.previous_scheme_version and i.source == "SCHEME"
                             and i.introduced_in_version == row.scheme_version),
    )


def _summary(row: SavedSchemeRow, items: Sequence[ChecklistItemRow],
             content: Optional[SchemeContent]) -> dict:
    current = [i for i in items if i.removed_in_version is None]
    notice = None
    if row.previous_scheme_version and not row.scheme_update_seen and row.scheme_version:
        notice = SchemeUpdateNotice(
            changed_at=_iso(row.scheme_changed_at),
            previous_version=_short(row.previous_scheme_version),
            current_version=_short(row.scheme_version),
            added=[i.label for i in items if i.source == "SCHEME" and i.introduced_in_version == row.scheme_version],
            removed=[i.label for i in items if i.removed_in_version == row.scheme_version],
        )
    s = content.scheme if content else None
    return dict(
        id=row.id, scheme_id=row.scheme_id, scheme_name=row.scheme_name,
        eligibility_status=row.eligibility_status, notes=row.notes, saved_at=_iso(row.saved_at),
        application_reference=row.application_reference,
        scheme_available=content is not None, scheme_status=s.status if s else None,
        scheme_version=_short(row.scheme_version), saved_scheme_version=_short(row.saved_scheme_version),
        scheme_data_version=row.scheme_data_version,
        official_url=s.official_url if s else None, application_url=s.application_url if s else None,
        progress=ProgressSummary(completed=sum(1 for i in current if i.completed), total=len(current),
                                 stage=_stage(items)),
        update_notice=notice,
    )


# ─── Loading (with sync to the current scheme version) ───────────────────────

async def _owner_pk(farmer_id: str) -> int:
    farmer = await profile_repo.get_farmer_by_farmer_id(farmer_id)
    if not farmer:
        raise SavedSchemeError("Farmer account not found.", "NOT_FOUND")
    return farmer.id


async def _sync(pk: int, rows: Sequence[SavedSchemeRow]) -> tuple[bool, Dict[str, SchemeContent]]:
    """Bring each saved scheme's checklist up to its scheme's current version."""
    contents = await repo.load_scheme_content([r.scheme_id for r in rows])
    changed = False
    for r in rows:
        c = contents.get(r.scheme_id)
        if c is None:                      # no longer in the database: keep the record as it is
            continue
        version = scheme_version(c)
        if version != r.scheme_version:
            await repo.sync_scheme_items(pk, r.id, r.scheme_version, version, c.scheme.data_version,
                                         c.scheme.name, build_checklist(c))
            changed = True
    return changed, contents


async def list_saved_schemes(farmer_id: str) -> List[SavedSchemeSummary]:
    pk = await _owner_pk(farmer_id)
    rows = await repo.list_saved(pk)
    changed, contents = await _sync(pk, rows)
    if changed:
        rows = await repo.list_saved(pk)
    items = await repo.list_items(pk, [r.id for r in rows])
    by_saved: Dict[int, List[ChecklistItemRow]] = {}
    for i in items:
        by_saved.setdefault(i.saved_scheme_id, []).append(i)
    return [SavedSchemeSummary(**_summary(r, by_saved.get(r.id, []), contents.get(r.scheme_id)))
            for r in rows]


async def _detail(pk: int, scheme_id: str) -> SavedSchemeDetail:
    row = await repo.get_saved(pk, scheme_id)
    if row is None:
        raise SavedSchemeError("You haven't saved this scheme.", "NOT_SAVED")
    changed, contents = await _sync(pk, [row])
    if changed:
        row = await repo.get_saved(pk, scheme_id)
        if row is None:                    # unsaved meanwhile
            raise SavedSchemeError("You haven't saved this scheme.", "NOT_SAVED")
    items = await repo.list_items(pk, [row.id])
    return SavedSchemeDetail(**_summary(row, items, contents.get(scheme_id)),
                             checklist=[_item(i, row) for i in items])


async def get_saved_scheme(farmer_id: str, scheme_id: str) -> SavedSchemeDetail:
    return await _detail(await _owner_pk(farmer_id), scheme_id)


# ─── Save / unsave ───────────────────────────────────────────────────────────

async def save_scheme(farmer_id: str, req: SaveSchemeRequest) -> SaveSchemeResult:
    """
    Save (bookmark) a scheme with its checklist. Saving one that is already saved
    changes nothing (notes and progress are kept) and returns created=False.
    """
    pk = await _owner_pk(farmer_id)
    c = (await repo.load_scheme_content([req.scheme_id])).get(req.scheme_id)
    if c is None:
        raise SavedSchemeError("This scheme isn't in SchemeSetu's scheme database, so it can't be saved.",
                               "SCHEME_NOT_FOUND")
    if c.scheme.status != "ACTIVE":
        raise SavedSchemeError("This scheme is not active at the moment, so it can't be saved.",
                               "SCHEME_INACTIVE")
    notes = (req.notes or "").strip() or None
    _, created = await repo.create_saved(pk, c.scheme.scheme_id, c.scheme.name, req.eligibility_status,
                                         notes, scheme_version(c), c.scheme.data_version, build_checklist(c))
    detail = await _detail(pk, c.scheme.scheme_id)
    return SaveSchemeResult(**detail.model_dump(), created=created)


async def unsave_scheme(farmer_id: str, scheme_id: str) -> bool:
    """Remove a saved scheme and its checklist. False if it wasn't saved."""
    return await repo.delete_saved(await _owner_pk(farmer_id), scheme_id)


async def update_saved_scheme(farmer_id: str, scheme_id: str,
                              req: SavedSchemeUpdateRequest) -> SavedSchemeDetail:
    pk = await _owner_pk(farmer_id)
    sent = req.model_fields_set
    changes = {f: getattr(req, f) for f in ("notes", "application_reference") if f in sent}
    if req.acknowledge_scheme_update:
        changes["scheme_update_seen"] = True
    if changes and await repo.update_saved(pk, scheme_id, changes) is None:
        raise SavedSchemeError("You haven't saved this scheme.", "NOT_SAVED")
    return await _detail(pk, scheme_id)


# ─── Checklist items ─────────────────────────────────────────────────────────

async def update_item(farmer_id: str, scheme_id: str, item_id: int,
                      req: ChecklistItemUpdateRequest) -> SavedSchemeDetail:
    """Mark an item complete / incomplete and/or set its note (null clears it)."""
    pk = await _owner_pk(farmer_id)
    changes = {f: getattr(req, f) for f in ("completed", "note") if f in req.model_fields_set}
    if await repo.update_item(pk, scheme_id, item_id, changes) is None:
        raise SavedSchemeError("Checklist item not found.", "ITEM_NOT_FOUND")
    return await _detail(pk, scheme_id)


async def add_milestone(farmer_id: str, scheme_id: str, req: MilestoneCreateRequest) -> SavedSchemeDetail:
    pk = await _owner_pk(farmer_id)
    try:
        item = await repo.add_milestone(pk, scheme_id, f"user:{uuid.uuid4().hex}", req.label, req.note,
                                        req.completed)
    except repo.MilestoneLimit:
        raise SavedSchemeError(f"You can add up to {repo.MAX_USER_MILESTONES} milestones per scheme.",
                               "LIMIT_REACHED")
    if item is None:
        raise SavedSchemeError("You haven't saved this scheme.", "NOT_SAVED")
    return await _detail(pk, scheme_id)


async def delete_milestone(farmer_id: str, scheme_id: str, item_id: int) -> SavedSchemeDetail:
    """Delete one of the farmer's own milestones (items from the scheme can only be unticked)."""
    pk = await _owner_pk(farmer_id)
    item = await repo.get_item(pk, scheme_id, item_id)
    if item is None:
        raise SavedSchemeError("Checklist item not found.", "ITEM_NOT_FOUND")
    if item.source != "USER":
        raise SavedSchemeError("Items from the scheme can't be deleted; mark them as not done instead.",
                               "NOT_DELETABLE")
    await repo.delete_milestone(pk, scheme_id, item_id)
    return await _detail(pk, scheme_id)
