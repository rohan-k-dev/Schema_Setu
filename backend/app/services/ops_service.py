"""
Operations dashboard for administrators (docs/ADMIN_OPERATIONS.md): system health,
scheme-corpus status, ingestion jobs, graph synchronisation, pending reviews, recent
errors, read-only data validation and conflict inspection.

Every public function authorizes the Principal itself (defence in depth). Each
dashboard section is computed independently: if one source is down, that section
says UNAVAILABLE and the others still show (no single failure blanks the page, and
nothing reports "all clear" when it could not check).
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List

from app.core import error_buffer
from app.core.config import APP_VERSION, settings
from app.core.logging import get_logger
from app.core.permissions import Permission, Principal, authorize
from app.core.redaction import redact
from app.database.connection import is_db_available
from app.database.repositories import audit_repository as audit_repo
from app.database.repositories import ops_repository as ops_repo

logger = get_logger(__name__)
STARTED = time.time()
LIST_CAP = 50


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


async def _section(name: str, fn: Callable[[], Awaitable[Dict[str, Any]]]) -> Dict[str, Any]:
    try:
        return {"status": "OK", **(await fn())}
    except Exception as exc:
        logger.error(f"Admin dashboard section '{name}' unavailable: {type(exc).__name__}")
        return {"status": "UNAVAILABLE", "message": f"Could not load {name} ({type(exc).__name__})."}


def expected_migration_head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    backend = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    cfg = Config(os.path.join(backend, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(backend, "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head()


# ─── sections ─────────────────────────────────────────────────────────────────

async def _system() -> Dict[str, Any]:
    from app.services.knowledge_graph_service import is_graph_available
    current = await ops_repo.migration_version() if is_db_available() else None
    head = expected_migration_head()
    warnings = []
    if current != head:
        warnings.append(f"Database migration is {current}, code expects {head}: run `alembic upgrade head`.")
    if settings.REVIEW_API_KEY and settings.ENVIRONMENT != "production":
        warnings.append("The development reviewer key (REVIEW_API_KEY) is enabled.")
    if not settings.SMTP_HOST:
        warnings.append("SMTP is not configured: account e-mails are only written to the server log.")
    return {
        "version": APP_VERSION, "environment": settings.ENVIRONMENT,
        "uptime_seconds": int(time.time() - STARTED),
        "database": {"connected": is_db_available(), "migration": current, "expected_migration": head},
        "knowledge_graph_loaded": is_graph_available(),
        # configured or not — never the values
        "external_services": {"groq": bool(settings.GROQ_API_KEY), "tavily": bool(settings.TAVILY_API_KEY),
                              "sarvam": bool(settings.SARVAM_API_KEY), "smtp": bool(settings.SMTP_HOST)},
        "warnings": warnings,
    }


async def _corpus() -> Dict[str, Any]:
    from app.services.admin_jobs import load_corpus_file, manifest_version
    schemes, manifest = load_corpus_file()
    db = await ops_repo.corpus_stats()
    cv = db.pop("corpus_version")
    file_version = manifest_version(manifest)
    return {
        "file": {"version": file_version, "schemes": len(schemes), "generated_at": manifest.get("generated_at"),
                 "content_hash": manifest.get("content_hash")},
        "database": {**{k: _iso(v) for k, v in db.items()},
                     "corpus_version": {k: _iso(v) for k, v in cv.items()} if cv else None},
        "in_step": bool(cv) and cv["version"] == file_version and db["schemes"] == len(schemes),
    }


async def _ingestion() -> Dict[str, Any]:
    jobs, total = await ops_repo.list_jobs(10, 0)
    return {
        "active_job": _job_out(await ops_repo.active_job()),
        "recent_jobs": [_job_out(j) for j in jobs], "jobs_total": total,
        "recent_import_runs": [{k: _iso(v) for k, v in r.items()} for r in await ops_repo.recent_ingestion_runs()],
    }


async def graph_sync() -> Dict[str, Any]:
    from app.knowledge_graph.schema import NodeType
    from app.services import knowledge_graph_service as kg
    repo = kg.get_graph_repo()
    health = kg.graph_health_check()
    if not kg.is_graph_available() or repo is None:
        return {"loaded": False, "in_sync": False, "message": "The Knowledge Graph is not loaded."}
    graph_ids = {n.split(":", 1)[1] for n in repo.get_nodes_by_type(NodeType.SCHEME)}
    db_ids = set(await ops_repo.scheme_index()) if is_db_available() else set()
    db_cv = (await ops_repo.corpus_stats())["corpus_version"] if is_db_available() else None
    missing, extra = sorted(db_ids - graph_ids), sorted(graph_ids - db_ids)
    same_version = bool(db_cv) and db_cv["version"] == repo.corpus_version
    return {
        "loaded": True, "nodes": health.get("nodes"), "edges": health.get("edges"),
        "graph_corpus_version": repo.corpus_version, "db_corpus_version": db_cv["version"] if db_cv else None,
        "generated_at": repo._metadata.get("generated_at"), "graph_hash": repo._metadata.get("graph_hash"),
        "stale_flag": health.get("stale", False),
        "schemes_missing_from_graph": missing[:LIST_CAP], "schemes_only_in_graph": extra[:LIST_CAP],
        "in_sync": same_version and not missing and not extra,
    }


async def _reviews() -> Dict[str, Any]:
    from app.models.review import ReviewStatus
    from app.services import review_service as rs
    cases = rs.get_all_cases()
    pending = [c for c in cases if c.status in (ReviewStatus.PENDING, ReviewStatus.IN_REVIEW)]
    by_reason: Dict[str, int] = {}
    for c in pending:
        by_reason[c.reason.value] = by_reason.get(c.reason.value, 0) + 1
    oldest = min((c.created_at for c in pending), default=None)
    return {"stats": rs.get_queue_stats(), "open_by_reason": by_reason, "oldest_open_created_at": oldest,
            "with_source_conflicts": sum(1 for c in cases if c.source_conflicts)}


async def _errors() -> Dict[str, Any]:
    _, total = error_buffer.buffer.page(1, 0)
    return {"buffered": total, "last_24h": error_buffer.last_24h(), "latest": error_buffer.latest(5),
            "note": "This server process only, since its last start; the server log is the full record."}


def _job_out(j):
    return {k: _iso(v) for k, v in j.items()} if j else None


async def overview(principal: Principal) -> Dict[str, Any]:
    authorize(principal, Permission.OPS_READ)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "system": await _section("system health", _system),
        "corpus": await _section("scheme corpus", _corpus),
        "ingestion": await _section("ingestion jobs", _ingestion),
        "graph": await _section("graph synchronisation", graph_sync),
        "reviews": await _section("pending reviews", _reviews),
        "errors": await _section("recent errors", _errors),
    }


# ─── errors, jobs ─────────────────────────────────────────────────────────────

def recent_errors(principal: Principal, limit: int, offset: int) -> Dict[str, Any]:
    authorize(principal, Permission.OPS_READ)
    rows, total = error_buffer.buffer.page(limit, offset)
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


async def list_jobs(principal: Principal, limit: int, offset: int) -> Dict[str, Any]:
    authorize(principal, Permission.OPS_READ)
    rows, total = await ops_repo.list_jobs(limit, offset)
    return {"items": [_job_out(j) for j in rows], "total": total, "limit": limit, "offset": offset}


async def get_job(principal: Principal, job_id: str):
    authorize(principal, Permission.OPS_READ)
    return _job_out(await ops_repo.get_job(job_id))


# ─── validation (read-only) ───────────────────────────────────────────────────

def _check(name: str, status: str, summary: str, items: List[Any] = ()) -> Dict[str, Any]:
    return {"name": name, "status": status, "summary": summary, "items": list(items)[:LIST_CAP]}


async def validate(principal: Principal) -> Dict[str, Any]:
    """Corpus file, database integrity, file ↔ database drift and graph checks. Changes nothing."""
    authorize(principal, Permission.OPS_VALIDATE)
    from app.eligibility.evaluator import _detect_rule_conflicts
    from app.services.admin_jobs import load_corpus_file, manifest_version, validate_corpus_data
    checks: List[Dict[str, Any]] = []

    async def guarded(name, fn):
        try:
            await fn()
        except Exception as exc:
            logger.error(f"Validation check '{name}' could not run: {type(exc).__name__}")
            checks.append(_check(name, "ERROR", f"Could not run ({type(exc).__name__})."))

    state: Dict[str, Any] = {}

    async def corpus_file():
        schemes, manifest = load_corpus_file()
        state["file_ids"] = {s["scheme_id"] for s in schemes}
        state["manifest"] = manifest
        v = validate_corpus_data(schemes)
        status = "FAIL" if v["errors"] else "WARN" if v["warnings"] else "PASS"
        checks.append(_check("corpus_file", status, f"{v['total']} schemes, {v['errors']} errors, "
                                                    f"{v['warnings']} warnings, {v['duplicates']} duplicates",
                             [i for i in v["issues"] if i["type"] == "ERROR"] or v["issues"]))

    async def database():
        found = await ops_repo.integrity_findings()
        rules = await ops_repo.rules_by_scheme()
        conflicts = [{"scheme_id": sid, **c} for sid, rs_ in rules.items() for c in _detect_rule_conflicts(rs_)]
        state["db_ids"] = set(await ops_repo.scheme_index())
        hard = found["rules_with_unknown_operator"] + found["active_without_sources"]
        checks.append(_check("rule_conflicts", "FAIL" if conflicts else "PASS",
                             f"{len(conflicts)} contradictory rule set(s)", conflicts))
        checks.append(_check("database_integrity", "FAIL" if hard else "PASS",
                             f"{len(found['active_without_sources'])} active without sources, "
                             f"{len(found['rules_with_unknown_operator'])} with UNKNOWN operators",
                             [{"check": k, "schemes": v} for k, v in found.items()
                              if k in ("active_without_sources", "rules_with_unknown_operator") and v]))
        soft = {k: v for k, v in found.items() if k not in ("active_without_sources", "rules_with_unknown_operator")}
        checks.append(_check("curation_flags", "WARN" if any(soft.values()) else "PASS",
                             ", ".join(f"{len(v)} {k.replace('_', ' ')}" for k, v in soft.items()),
                             [{"check": k, "schemes": v[:LIST_CAP]} for k, v in soft.items() if v]))

    async def drift():
        if "file_ids" not in state or "db_ids" not in state:
            checks.append(_check("file_vs_database", "ERROR", "Skipped: an earlier check could not run."))
            return
        missing = sorted(state["file_ids"] - state["db_ids"])
        extra = sorted(state["db_ids"] - state["file_ids"])
        cv = (await ops_repo.corpus_stats())["corpus_version"]
        same = bool(cv) and cv["version"] == manifest_version(state["manifest"])
        status = "FAIL" if missing else "WARN" if extra or not same else "PASS"
        checks.append(_check("file_vs_database", status,
                             f"{len(missing)} in the file but not imported, {len(extra)} only in the database; "
                             f"database corpus {cv['version'] if cv else 'none'} vs file "
                             f"{manifest_version(state['manifest'])}",
                             [{"missing_in_database": missing, "only_in_database": extra}]))

    async def graph():
        from app.knowledge_graph.validator import validate_graph
        from app.services import knowledge_graph_service as kg
        sync = await graph_sync()
        repo = kg.get_graph_repo()
        if not sync["loaded"] or repo is None:
            checks.append(_check("knowledge_graph", "FAIL", "The Knowledge Graph is not loaded."))
            return
        result = validate_graph(repo.graph, corpus_scheme_ids=sorted(state.get("file_ids", [])) or None)
        status = "FAIL" if result.errors else "WARN" if (result.warnings or not sync["in_sync"]) else "PASS"
        checks.append(_check("knowledge_graph", status,
                             f"{len(result.errors)} errors, {len(result.warnings)} warnings; "
                             f"{'in sync' if sync['in_sync'] else 'NOT in sync'} with the database",
                             [redact(e, 200) for e in result.errors] + [redact(w, 200) for w in result.warnings]))

    for name, fn in (("corpus_file", corpus_file), ("database", database), ("file_vs_database", drift),
                     ("knowledge_graph", graph)):
        await guarded(name, fn)

    order = {"PASS": 0, "WARN": 1, "FAIL": 2, "ERROR": 3}
    overall = max((c["status"] for c in checks), key=order.get, default="ERROR")
    report = {"overall": overall, "checked_at": datetime.now(timezone.utc).isoformat(), "checks": checks}
    await audit_repo.record(principal, "VALIDATION_RUN", "corpus", None,
                            {"overall": overall, "checks": {c["name"]: c["status"] for c in checks}},
                            outcome="SUCCESS" if overall in ("PASS", "WARN") else "FAILURE")
    return report


# ─── conflicts (read-only) ────────────────────────────────────────────────────

async def conflicts(principal: Principal) -> Dict[str, Any]:
    """Source conflicts seen by retrieval (DB vs web, kept on review cases), rule conflicts, flags."""
    authorize(principal, Permission.OPS_READ)
    from app.eligibility.evaluator import _detect_rule_conflicts
    from app.services import review_service as rs
    source = []
    for c in rs.get_all_cases():
        for sc in c.source_conflicts or []:
            values = sc.get("values") or {}
            source.append({
                "case_id": c.case_id, "case_status": c.status.value, "created_at": c.created_at,
                "scheme_id": sc.get("scheme_id"), "field": sc.get("field"),
                "values": {str(k): redact(v, 300) for k, v in values.items()} if isinstance(values, dict)
                else redact(values, 300),
                "resolution": "The database value is canonical; correct the corpus if the web value is right.",
            })
    out: Dict[str, Any] = {"source_conflicts": source[:200], "source_conflicts_total": len(source)}
    try:
        rules = await ops_repo.rules_by_scheme()
        index = await ops_repo.scheme_index()
        out["rule_conflicts"] = [{"scheme_id": sid, **c} for sid, r in rules.items()
                                 for c in _detect_rule_conflicts(r)]
        out["flagged_schemes"] = [
            {"scheme_id": sid, "name": s["name"], "status": s["status"], "needs_review": s["needs_review"],
             "possible_duplicate": s["possible_duplicate"], "review_notes": redact(s["review_notes"], 300)
             if s["review_notes"] else None}
            for sid, s in sorted(index.items()) if s["needs_review"] or s["possible_duplicate"]][:200]
    except Exception as exc:
        logger.error(f"Conflict inspection: database part unavailable: {type(exc).__name__}")
        out["rule_conflicts"] = out["flagged_schemes"] = None
        out["database_status"] = "UNAVAILABLE"
    return out
