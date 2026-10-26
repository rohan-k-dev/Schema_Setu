"""
Scheme-update pipeline (docs/SCHEME_UPDATES.md):

  1. DETECT   a candidate corpus (newly scraped + normalised, dropped in data/incoming/) is
              compared with the last verified corpus (data/validated/schemes.json). Invalid
              records are refused; meaningful changes are stored PENDING with provenance.
  2. VERIFY   an administrator approves or rejects each change. Nothing scraped is trusted
              automatically: consequential changes (eligibility, benefits, states, status, new /
              missing schemes) need an explicit confirmation and a note.
  3. PUBLISH  (admin job PUBLISH_CHANGES) only approved changes are merged into the verified
              corpus, which is validated, written atomically (new version + snapshot) and
              imported into the database in one transaction.
  4. NOTIFY   only then, farmers who saved or follow an affected scheme are notified (in-app,
              e-mail, SMS per their preferences) — once per change set.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core import request_context
from app.core.logging import get_logger
from app.core.permissions import Permission, Principal, authorize
from app.database.repositories import audit_repository as audit_repo
from app.database.repositories import change_repository as changes_repo
from app.database.repositories import notification_repository as notif_repo
from app.services import change_detection as cd

logger = get_logger(__name__)

SOURCE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,100}\.json$")
MAX_CANDIDATE_BYTES = 20 * 1024 * 1024


class UpdateRejected(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


# ─── data locations (tests point these at a temporary folder) ─────────────────

def data_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data"))


def incoming_dir() -> str:
    return os.path.join(data_root(), "incoming")


def _read_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_verified() -> tuple[list, dict]:
    root = data_root()
    schemes = _read_json(os.path.join(root, "validated", "schemes.json"))
    manifest_path = os.path.join(root, "metadata", "corpus_manifest.json")
    manifest = _read_json(manifest_path) if os.path.exists(manifest_path) else {}
    return schemes, manifest


def list_incoming() -> List[Dict[str, Any]]:
    d = incoming_dir()
    if not os.path.isdir(d):
        return []
    return [{"name": n, "bytes": os.path.getsize(os.path.join(d, n)),
             "modified_at": datetime.fromtimestamp(os.path.getmtime(os.path.join(d, n)), timezone.utc).isoformat()}
            for n in sorted(os.listdir(d)) if SOURCE_NAME.match(n)]


def _read_candidate(source_name: str) -> tuple[list, str]:
    if not SOURCE_NAME.match(source_name or ""):
        raise UpdateRejected("BAD_SOURCE", "Use the name of a .json file in data/incoming/.")
    path = os.path.join(incoming_dir(), source_name)        # the name can't contain a path separator
    if not os.path.isfile(path):
        raise UpdateRejected("NOT_FOUND", f"{source_name} is not in data/incoming/.")
    if os.path.getsize(path) > MAX_CANDIDATE_BYTES:
        raise UpdateRejected("TOO_LARGE", "The candidate file is larger than 20 MB.")
    raw = open(path, "rb").read()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise UpdateRejected("BAD_JSON", "The candidate file is not valid UTF-8 JSON.")
    if not isinstance(data, list):
        raise UpdateRejected("BAD_JSON", "The candidate file must be a JSON list of schemes.")
    return data, hashlib.sha256(raw).hexdigest()


def _validate_candidate(data: list) -> tuple[list, list]:
    """Records that parse as CanonicalScheme (normalised form) and have no validation errors."""
    from app.ingestion import CanonicalScheme
    from app.ingestion.validator import validate_corpus
    good, invalid, seen = [], [], set()
    for i, item in enumerate(data):
        sid = item.get("scheme_id") if isinstance(item, dict) else None
        try:
            parsed = CanonicalScheme(**item)
        except Exception as exc:
            invalid.append({"index": i, "scheme_id": sid, "reason": f"not a valid scheme record ({type(exc).__name__})"})
            continue
        if parsed.scheme_id in seen:
            invalid.append({"index": i, "scheme_id": sid, "reason": "duplicate scheme_id"})
            continue
        seen.add(parsed.scheme_id)
        good.append((parsed, parsed.model_dump(mode="json")))
    report = validate_corpus([p for p, _ in good])
    bad = {x.scheme_id for x in report.issues if x.issue_type == "ERROR"}
    for sid in sorted(bad):
        invalid.append({"index": None, "scheme_id": sid, "reason": "validation errors"})
    return [d for p, d in good if p.scheme_id not in bad], invalid


# ─── 1. detect ────────────────────────────────────────────────────────────────

async def detect(principal: Principal, source_name: str) -> Dict[str, Any]:
    authorize(principal, Permission.SCHEME_CHANGES_REVIEW)
    from app.services.corpus_import_service import manifest_version
    data, sha = _read_candidate(source_name)
    candidate, invalid = _validate_candidate(data)
    verified, manifest = load_verified()
    if invalid:                       # never treat a broken record as "the scheme disappeared"
        bad_ids = {x["scheme_id"] for x in invalid if x["scheme_id"]}
        verified_for_diff = [s for s in verified if s["scheme_id"] not in bad_ids]
    else:
        verified_for_diff = verified
    found, warnings = cd.diff_corpora(verified_for_diff, candidate, source_name, sha)
    batch = {"id": str(uuid.uuid4()), "source_name": source_name, "source_sha256": sha,
             "base_version": manifest_version(manifest), "candidate_count": len(data),
             "invalid_records": invalid[:200], "warnings": warnings, "detected_by": principal.label,
             "correlation_id": request_context.current()}
    rows = [{"scheme_id": c.scheme_id, "scheme_name": c.scheme_name, "category": c.category,
             "consequential": c.consequential, "summary": c.summary, "before": c.before, "after": c.after,
             "fingerprint": c.fingerprint, "provenance": c.provenance} for c in found]
    created_batch, new, dupes = await changes_repo.create_batch(batch, rows)
    await audit_repo.record(principal, "CHANGES_DETECTED", "change_batch", batch["id"],
                            {"source": source_name, "source_sha256": sha, "new_changes": new, "duplicates": dupes,
                             "invalid_records": len(invalid), "warnings": len(warnings)})
    return {"batch_id": batch["id"], "new_changes": new, "duplicates_skipped": dupes,
            "invalid_records": invalid[:50], "warnings": warnings,
            "consequential": sum(1 for c in found if c.consequential)}


# ─── 2. verify ────────────────────────────────────────────────────────────────

async def review(principal: Principal, change_id: int, decision: str, note: Optional[str],
                 confirm_consequential: bool) -> dict:
    authorize(principal, Permission.SCHEME_CHANGES_REVIEW)
    change = await changes_repo.get_change(change_id)
    if change is None:
        raise UpdateRejected("NOT_FOUND", "Change not found.")
    if decision == "APPROVED" and change["consequential"]:
        if not confirm_consequential or not note or len(note.strip()) < 10:
            await audit_repo.record(principal, "CHANGE_REVIEWED", "scheme_change", str(change_id),
                                    {"decision": decision, "refused": "CONFIRMATION_REQUIRED"}, outcome="FAILURE")
            raise UpdateRejected("CONFIRMATION_REQUIRED",
                                 "This change affects eligibility or benefits: check it against the official source, "
                                 "then approve with confirm_consequential and a note (at least 10 characters).")
    row = await changes_repo.review(change_id, decision, principal.label, note)
    if row is None:
        await audit_repo.record(principal, "CHANGE_REVIEWED", "scheme_change", str(change_id),
                                {"decision": decision, "refused": "NOT_PENDING"}, outcome="FAILURE")
        raise UpdateRejected("NOT_PENDING", "Only pending changes in an open batch can be reviewed.")
    await audit_repo.record(principal, "CHANGE_REVIEWED", "scheme_change", str(change_id),
                            {"decision": decision, "scheme_id": row["scheme_id"], "category": row["category"],
                             "consequential": row["consequential"]})
    return row


async def discard(principal: Principal, batch_id: str) -> None:
    authorize(principal, Permission.SCHEME_CHANGES_REVIEW)
    if not await changes_repo.discard_batch(batch_id):
        raise UpdateRejected("NOT_OPEN", "Only an open batch can be discarded.")
    await audit_repo.record(principal, "CHANGE_BATCH_DISCARDED", "change_batch", batch_id)


# ─── 3. publish (run by the admin job PUBLISH_CHANGES) ────────────────────────

def _bump(version: str) -> str:
    parts = (version or "1.0.0").split(".")
    while len(parts) < 3:
        parts.append("0")
    try:
        parts[2] = str(int(parts[2]) + 1)
    except ValueError:
        parts.append("1")
    return ".".join(parts[:3])


def _atomic_write(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.incoming"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def write_verified(schemes: list, manifest: dict, version: str) -> Dict[str, Any]:
    """New verified corpus files (atomic per file) + a dated snapshot; the old files are backed up."""
    root = data_root()
    blob = json.dumps(schemes, indent=2, ensure_ascii=False)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    backup = os.path.join(root, "backups", f"corpus-{stamp}")
    os.makedirs(backup, exist_ok=True)
    for rel in (("validated", "schemes.json"), ("metadata", "corpus_manifest.json")):
        src = os.path.join(root, *rel)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(backup, rel[-1]))
    new_manifest = {**manifest, "corpus_version": version, "generated_at": datetime.now(timezone.utc).isoformat(),
                    "total_scheme_count": len(schemes),
                    "active_scheme_count": sum(1 for s in schemes if cd._v(s.get("status")) == "ACTIVE"),
                    "content_hash": hashlib.sha256(blob.encode()).hexdigest()[:16]}
    new_manifest.pop("version", None)
    _atomic_write(os.path.join(root, "validated", "schemes.json"), schemes)
    _atomic_write(os.path.join(root, "metadata", "corpus_manifest.json"), new_manifest)
    snap = os.path.join(root, "snapshots", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    _atomic_write(os.path.join(snap, "schemes.json"), schemes)
    _atomic_write(os.path.join(snap, "manifest.json"), new_manifest)
    return {"version": version, "backup": os.path.relpath(backup, root)}


def restore_verified(backup_rel: str) -> None:
    root = data_root()
    for name, rel in (("schemes.json", ("validated", "schemes.json")),
                      ("corpus_manifest.json", ("metadata", "corpus_manifest.json"))):
        src = os.path.join(root, backup_rel, name)
        if os.path.exists(src):
            _atomic_write(os.path.join(root, *rel), _read_json(src))


async def publish(batch_id: str, dry_run: bool, actor: Principal) -> Dict[str, Any]:
    from app.services.admin_jobs import JobRefused, validate_corpus_data
    from app.services.corpus_import_service import manifest_version
    batch = await changes_repo.get_batch(batch_id)
    if batch is None or batch["status"] != "OPEN":
        raise JobRefused("The batch doesn't exist or isn't open.")
    if batch["pending"]:
        raise JobRefused(f"{batch['pending']} change(s) are still pending: approve or reject every change first.")
    approved = await changes_repo.approved_changes(batch_id)
    if not approved:
        raise JobRefused("Nothing to publish: no change in this batch was approved.")
    data, sha = _read_candidate(batch["source_name"])
    if sha != batch["source_sha256"]:
        raise JobRefused("The candidate file changed after detection; detect again.")
    verified, manifest = load_verified()
    if manifest_version(manifest) != batch["base_version"]:
        raise JobRefused("The verified corpus changed since detection (another batch was published); "
                         "detect again from the candidate.")
    candidate, _ = _validate_candidate(data)
    today = datetime.now(timezone.utc).date().isoformat()
    merged = cd.apply_approved(verified, candidate, approved, today)
    check = validate_corpus_data(merged)
    if check["errors"]:
        raise JobRefused(f"The merged corpus has {check['errors']} validation error(s); nothing was published.")
    version = _bump(manifest_version(manifest))
    plan = {"version": version, "approved_changes": len(approved),
            "schemes_affected": sorted({c["scheme_id"] for c in approved})}
    if dry_run:
        return {**plan, "dry_run": True}
    written = write_verified(merged, manifest, version)
    from app.services.corpus_import_service import import_corpus
    try:
        stats = await import_corpus(dry_run=False, force=False)        # one transaction
    except Exception as exc:
        restore_verified(written["backup"])                            # files and database stay in step
        logger.error(f"Publish of batch {batch_id}: import failed ({type(exc).__name__}); files restored")
        raise JobRefused("The database import failed, so nothing was published (the verified files were "
                         "restored). Farmers were not notified.")
    try:
        from app.ingestion.corpus_loader import get_corpus_loader
        get_corpus_loader().load()                         # local scheme search sees the new data
    except Exception as exc:
        logger.warning(f"Corpus search index not reloaded: {type(exc).__name__}")
    published = await changes_repo.mark_published(batch_id, version)
    fan = await notify(batch_id, published)
    await audit_repo.record(actor, "CHANGES_PUBLISHED", "change_batch", batch_id,
                            {"version": version, "changes": len(published), "notifications": fan["created"]})
    return {**plan, **written, "import": stats.to_dict(), "notifications": fan,
            "next_step": "Rebuild the Knowledge Graph so retrieval uses the new data."}


# ─── 4. notify ────────────────────────────────────────────────────────────────

def _message(scheme_name: str, changes: List[dict]) -> tuple[str, str, bool]:
    consequential = any(c["consequential"] for c in changes)
    cats = []
    for c in changes:
        if cd.LABEL[c["category"]] not in cats:
            cats.append(cd.LABEL[c["category"]])
    title = f"{scheme_name}: {'important update' if consequential else 'update'}"
    body = (f"Official information for {scheme_name} has changed:\n"
            + "".join(f"- {c}\n" for c in cats)
            + ("Please check whether you still qualify before applying.\n" if consequential else "")
            + "This change was checked by the SchemeSetu team against the official source. Open SchemeSetu to see "
              "the current details.")
    return title, body, consequential


async def notify(batch_id: str, published: List[dict]) -> Dict[str, int]:
    """One notification per (account, scheme) for this batch — re-running creates no duplicates."""
    by_scheme: Dict[str, List[dict]] = {}
    for c in published:
        by_scheme.setdefault(c["scheme_id"], []).append(c)
    created = skipped = 0
    for row in await notif_repo.audience(list(by_scheme)):
        changes = by_scheme[row["scheme_id"]]
        title, body, consequential = _message(changes[0]["scheme_name"], changes)
        if row["consequential_only"] and not consequential:
            skipped += 1
            continue
        channels = [ch for ch, on in (("EMAIL", row["email"]), ("SMS", row["sms"])) if on]
        if not row["in_app"] and not channels:
            skipped += 1
            continue
        nid = await notif_repo.create_notification({
            "farmer_pk": row["farmer_pk"], "scheme_id": row["scheme_id"], "batch_id": batch_id,
            "change_ids": sorted(c["id"] for c in changes), "title": title, "body": body,
            "consequential": consequential, "show_in_app": row["in_app"],
            "dedupe_key": f"changes:{batch_id}:{row['scheme_id']}"}, channels)
        created += 1 if nid else 0
        skipped += 0 if nid else 1
    return {"created": created, "skipped": skipped}


# ─── reads for the admin UI ───────────────────────────────────────────────────

async def batches(principal: Principal, limit: int, offset: int):
    authorize(principal, Permission.SCHEME_CHANGES_REVIEW)
    return await changes_repo.list_batches(limit, offset)


async def changes(principal: Principal, batch_id: Optional[str], status: Optional[str], limit: int, offset: int):
    authorize(principal, Permission.SCHEME_CHANGES_REVIEW)
    return await changes_repo.list_changes(batch_id, status, limit, offset)
