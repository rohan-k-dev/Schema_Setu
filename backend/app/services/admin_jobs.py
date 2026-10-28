"""
Admin jobs: corpus ingestion and Knowledge Graph rebuild (docs/ADMIN_OPERATIONS.md).

Safety rules, all enforced here on the server:
  - administrators only (OPS_RUN_JOBS), checked again in start_job;
  - ONE job at a time (partial unique index on admin_jobs) — a second request gets 409;
  - dry run by default; a real run needs ``confirm`` equal to the job kind and a reason;
  - the validated corpus file must pass validation first, or nothing is changed;
  - ingestion is the existing transactional, idempotent importer (all-or-nothing; it never
    deletes schemes);
  - a graph rebuild is built and validated in a staging folder, then swapped in with
    directory renames; the previous graph is kept as a backup and restored automatically if
    the new one fails to load;
  - every request, success and failure is audited with the request's correlation id; jobs
    left queued / running by a restart are marked FAILED at startup.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core import request_context
from app.core.logging import get_logger
from app.core.permissions import Permission, Principal, authorize
from app.core.redaction import redact, sanitize
from app.database.repositories import audit_repository as audit_repo
from app.database.repositories import ops_repository as ops_repo

logger = get_logger(__name__)

KINDS = ("IMPORT_CORPUS", "REBUILD_GRAPH", "PUBLISH_CHANGES")
KEEP_BACKUPS = 5
SYSTEM = Principal(role=None, label="system", via="system")


class JobRejected(Exception):
    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)


class JobRefused(Exception):
    """A job stopped by a safety check before changing anything (client-safe message)."""


# ─── shared inputs ────────────────────────────────────────────────────────────

def _val(x):
    return x.get("value") if isinstance(x, dict) else x


def manifest_version(manifest: dict) -> str:
    from app.services.corpus_import_service import manifest_version as mv
    return mv(manifest)


def load_corpus_file() -> tuple[list, dict]:
    from app.services.corpus_import_service import load_corpus
    return load_corpus()


def validate_corpus_data(schemes: list) -> Dict[str, Any]:
    """The phase 1 validator over the validated corpus file (read-only)."""
    from app.ingestion import CanonicalScheme
    from app.ingestion.validator import validate_corpus
    parsed, parse_errors = [], []
    for i, item in enumerate(schemes):
        try:
            parsed.append(CanonicalScheme(**item))
        except Exception as exc:
            parse_errors.append(f"record {i} ({item.get('scheme_id', '?')}): {type(exc).__name__}")
    report = validate_corpus(parsed)
    issues = [{"scheme_id": x.scheme_id, "field": x.field, "type": x.issue_type, "message": redact(x.message, 200)}
              for x in report.issues][:100]
    return {
        "total": len(schemes), "errors": report.error_count + len(parse_errors),
        "warnings": report.warning_count, "duplicates": report.duplicate_count,
        "parse_errors": parse_errors[:20], "issues": issues,
    }


def graph_base_dir() -> str:
    from app.knowledge_graph.serializer import _graph_data_dir
    return _graph_data_dir()


# ─── IMPORT_CORPUS ────────────────────────────────────────────────────────────

async def _import_plan(schemes: list) -> Dict[str, Any]:
    index = await ops_repo.scheme_index()
    file_ids = [s["scheme_id"] for s in schemes]
    resets = []
    for s in schemes:
        db = index.get(s["scheme_id"])
        if db and (db["status"] != (_val(s.get("status")) or "ACTIVE")
                   or bool(db["needs_review"]) != bool(s.get("needs_review", False))):
            resets.append(s["scheme_id"])
    return {
        "to_insert": sorted(set(file_ids) - set(index)),
        "to_update": len(set(file_ids) & set(index)),
        "kept_not_in_file": sorted(set(index) - set(file_ids)),   # the importer never deletes schemes
        "curation_reset": sorted(resets),                         # admin status / needs-review overwritten
    }


async def run_import(dry_run: bool) -> Dict[str, Any]:
    schemes, manifest = await asyncio.to_thread(load_corpus_file)
    validation = await asyncio.to_thread(validate_corpus_data, schemes)
    if validation["errors"]:
        raise JobRefused(f"The corpus file has {validation['errors']} validation error(s); nothing was imported. "
                         "Run Validate for details.")
    plan = await _import_plan(schemes)
    base = {"corpus_version": manifest_version(manifest), "schemes_in_file": len(schemes),
            "validation": {k: validation[k] for k in ("total", "errors", "warnings", "duplicates")}, "plan": plan}
    if dry_run:
        return base
    from app.services.corpus_import_service import import_corpus
    stats = await import_corpus(dry_run=False, force=False)      # one transaction; any error rolls back
    from app.services import ops_service
    return {**base, "import": stats.to_dict(), "graph_sync": (await ops_service.graph_sync())}


# ─── REBUILD_GRAPH ────────────────────────────────────────────────────────────

def _build_graph(schemes: list, corpus_version: str):
    from app.knowledge_graph.builder import KnowledgeGraphBuilder
    from app.knowledge_graph.validator import validate_graph
    builder = KnowledgeGraphBuilder()
    graph = builder.build_from_corpus(schemes, corpus_version=corpus_version)
    stats = builder.get_stats()
    result = validate_graph(graph, corpus_scheme_ids=[s["scheme_id"] for s in schemes])
    return graph, stats, result


def _current_metadata(base: str) -> Optional[dict]:
    path = os.path.join(base, "current", "metadata.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _prune_backups(base: str) -> None:
    root = os.path.join(base, "backups")
    if os.path.isdir(root):
        for old in sorted(os.listdir(root))[:-KEEP_BACKUPS]:
            shutil.rmtree(os.path.join(root, old), ignore_errors=True)


# graph.json first: the loader needs it; metadata follows, then the rest
_INSTALL_ORDER = ("graph.json", "metadata.json", "graph_stats.json")


def _install_files(src_dir: str, dst_dir: str) -> None:
    """
    Put src_dir's files into dst_dir, each with an atomic os.replace. Directories are not
    renamed: on Docker's overlay filesystem a directory from the image can't be (EXDEV),
    and copying the source next to its target first keeps every rename on one filesystem.
    Files in dst_dir that src_dir doesn't have (e.g. an old validation report) are removed.
    """
    os.makedirs(dst_dir, exist_ok=True)
    names = sorted(os.listdir(src_dir), key=lambda n: (_INSTALL_ORDER.index(n) if n in _INSTALL_ORDER else 9, n))
    for name in names:
        tmp = os.path.join(dst_dir, f".{name}.incoming")
        shutil.copyfile(os.path.join(src_dir, name), tmp)
        os.replace(tmp, os.path.join(dst_dir, name))
    for stale in set(os.listdir(dst_dir)) - set(names):
        if not stale.startswith("."):
            os.remove(os.path.join(dst_dir, stale))


def _swap_in(base: str, staging: str, stamp: str) -> Optional[str]:
    """Replace data/graph/current with the staged graph; returns the backup path (or None)."""
    from app.knowledge_graph.serializer import load_graph_snapshot
    load_graph_snapshot(staging)                                  # the staged files must load
    current = os.path.join(base, "current")
    backup = None
    if os.path.isdir(current):
        backup = os.path.join(base, "backups", stamp)
        shutil.copytree(current, backup)                         # copy, so `current` is never missing
    try:
        _install_files(os.path.join(staging, "current"), current)
    except Exception:
        if backup:                                                # never leave a half-installed graph
            _install_files(backup, current)
        raise
    for day in os.listdir(os.path.join(staging, "snapshots")):    # keep the dated snapshot too
        _install_files(os.path.join(staging, "snapshots", day), os.path.join(base, "snapshots", day))
    shutil.rmtree(staging, ignore_errors=True)
    return backup


def _restore(base: str, backup: Optional[str]) -> None:
    if backup and os.path.isdir(backup):
        _install_files(backup, os.path.join(base, "current"))


async def run_graph_rebuild(dry_run: bool, job_id: str) -> Dict[str, Any]:
    from app.knowledge_graph.serializer import compute_graph_hash, graph_to_json, save_graph_snapshot
    from app.services import knowledge_graph_service as kg

    schemes, manifest = await asyncio.to_thread(load_corpus_file)
    version = manifest_version(manifest)
    graph, stats, result = await asyncio.to_thread(_build_graph, schemes, version)
    if not result.is_valid:
        raise JobRefused(f"The new graph failed validation ({len(result.errors)} error(s)); the current graph "
                         f"was not changed. First: {redact(result.errors[0], 200)}")
    base = graph_base_dir()
    before = _current_metadata(base)
    new_hash = compute_graph_hash(graph_to_json(graph))
    summary = {
        "corpus_version": version, "nodes": stats.get("total_nodes"), "edges": stats.get("total_edges"),
        "graph_hash": new_hash, "validation": {"errors": 0, "warnings": len(result.warnings)},
        "previous": {k: before.get(k) for k in ("graph_hash", "node_count", "edge_count", "corpus_version",
                                                "generated_at")} if before else None,
        "changed": not before or before.get("graph_hash") != new_hash,
    }
    if dry_run:
        return summary

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + f"-{job_id[:8]}"
    staging = os.path.join(base, f".staging-{job_id[:8]}")
    shutil.rmtree(staging, ignore_errors=True)
    try:
        await asyncio.to_thread(save_graph_snapshot, graph, stats, version, "1.0.0", staging)
        backup = await asyncio.to_thread(_swap_in, base, staging, stamp)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    if not kg.init_knowledge_graph():                             # reload in this process
        await asyncio.to_thread(_restore, base, backup)
        kg.init_knowledge_graph()
        raise JobRefused("The new graph could not be loaded; the previous graph was restored.")
    await asyncio.to_thread(_prune_backups, base)
    return {**summary, "backup": os.path.relpath(backup, base) if backup else None,
            "loaded": kg.graph_health_check()}


# ─── lifecycle ────────────────────────────────────────────────────────────────

async def start_job(principal: Principal, kind: str, dry_run: bool, reason: str,
                    confirm: Optional[str], batch_id: Optional[str] = None) -> dict:
    authorize(principal, Permission.OPS_RUN_JOBS)
    details = {"kind": kind, "dry_run": dry_run, "reason": reason, **({"batch_id": batch_id} if batch_id else {})}
    try:
        if kind not in KINDS:
            raise JobRejected("BAD_KIND", "Unknown job kind.")
        if (kind == "PUBLISH_CHANGES") != bool(batch_id):
            raise JobRejected("BAD_PARAMS", "batch_id is required for PUBLISH_CHANGES (and only for it).")
        if kind == "PUBLISH_CHANGES":
            authorize(principal, Permission.SCHEME_CHANGES_REVIEW)
        if not dry_run and confirm != kind:
            raise JobRejected("CONFIRM_REQUIRED",
                              f"A real run changes data: send confirm equal to \"{kind}\" (or use a dry run).")
        try:
            job = await ops_repo.create_job(kind, dry_run, reason, principal.account_pk, principal.label,
                                            request_context.current(),
                                            {"batch_id": batch_id} if batch_id else None)
        except ops_repo.JobInProgress:
            active = await ops_repo.active_job()
            raise JobRejected("JOB_IN_PROGRESS", "Another job is already queued or running"
                              + (f" ({active['kind']}, {active['id']})." if active else "."))
    except JobRejected as exc:
        await audit_repo.record(principal, "JOB_REQUESTED", "admin_job", None,
                                {**details, "refused": exc.code}, outcome="FAILURE")
        raise
    await audit_repo.record(principal, "JOB_REQUESTED", "admin_job", job["id"], details)
    return job


async def run_job(job_id: str, principal: Principal, correlation_id: Optional[str]) -> None:
    """Executed after the response (BackgroundTasks). Never raises."""
    token = request_context.bind(correlation_id)
    try:
        job = await ops_repo.get_job(job_id)
        if not job or not await ops_repo.mark_running(job_id):
            return
        try:
            if job["kind"] == "IMPORT_CORPUS":
                result = await run_import(job["dry_run"])
            elif job["kind"] == "PUBLISH_CHANGES":
                from app.services import notification_service, scheme_update_service
                result = await scheme_update_service.publish((job.get("params") or {}).get("batch_id"),
                                                             job["dry_run"], principal)
                if not job["dry_run"]:
                    result["deliveries"] = await notification_service.dispatch_due()
            else:
                result = await run_graph_rebuild(job["dry_run"], job_id)
            result = sanitize(result)
            await ops_repo.finish(job_id, "SUCCEEDED", result, None)
            await audit_repo.record(principal, "JOB_SUCCEEDED", "admin_job", job_id,
                                    {"kind": job["kind"], "dry_run": job["dry_run"]})
        except JobRefused as exc:
            await _fail(job, principal, str(exc))
        except Exception as exc:
            logger.error(f"Admin job {job_id} ({job['kind']}) failed: {type(exc).__name__}: {exc}")
            await _fail(job, principal, f"Unexpected {type(exc).__name__}. Nothing was committed if the error "
                                        f"happened during the import transaction. See recent errors "
                                        f"(correlation id {correlation_id}).")
    except Exception as exc:                       # even bookkeeping failed: the server log has it
        logger.error(f"Admin job {job_id}: could not record the outcome: {type(exc).__name__}")
    finally:
        request_context.reset(token)


async def _fail(job: dict, principal: Principal, message: str) -> None:
    await ops_repo.finish(job["id"], "FAILED", None, redact(message, 1000))
    await audit_repo.record(principal, "JOB_FAILED", "admin_job", job["id"],
                            {"kind": job["kind"], "dry_run": job["dry_run"], "error": message}, outcome="FAILURE")


async def fail_interrupted_jobs() -> List[dict]:
    from app.database.connection import is_db_available
    if not is_db_available():
        return []
    jobs = await ops_repo.fail_interrupted()
    for job in jobs:
        logger.warning(f"Admin job {job['id']} ({job['kind']}) was interrupted by a restart; marked FAILED.")
        await audit_repo.record(SYSTEM, "JOB_FAILED", "admin_job", job["id"],
                                {"kind": job["kind"], "error": "interrupted by restart"}, outcome="FAILURE")
    return jobs
