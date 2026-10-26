"""
OpsRepository — SQL for the administrator operations dashboard
(docs/ADMIN_OPERATIONS.md): corpus / ingestion status, data-integrity queries and
the admin_jobs table.

Status queries are read-only. Database errors are raised (never turned into "no
data"), so the dashboard can say "unavailable" instead of showing a false all-clear.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

from psycopg import errors as pg_errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.database.connection import get_db_connection
from app.models.db import EligibilityRuleRow

JOB_COLUMNS = ("id", "kind", "status", "dry_run", "reason", "requested_by", "correlation_id", "created_at",
               "started_at", "finished_at", "result", "error", "params")


class JobInProgress(Exception):
    """Another admin job is queued or running (one at a time)."""


async def _all(query: str, params: tuple = ()) -> List[dict]:
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query, params)
            return await cur.fetchall()


async def _one(query: str, params: tuple = ()) -> Optional[dict]:
    rows = await _all(query, params)
    return rows[0] if rows else None


# ─── status ───────────────────────────────────────────────────────────────────

async def migration_version() -> Optional[str]:
    row = await _one("SELECT version_num FROM alembic_version LIMIT 1")
    return row["version_num"] if row else None


async def corpus_stats() -> Dict[str, Any]:
    by_status = {r["status"]: r["n"] for r in await _all(
        "SELECT status, count(*) AS n FROM schemes GROUP BY status")}
    row = await _one("""
        SELECT count(*) AS schemes,
               count(*) FILTER (WHERE needs_review) AS needs_review,
               count(*) FILTER (WHERE possible_duplicate) AS possible_duplicates,
               count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM eligibility_rules r WHERE r.scheme_id = s.id))
                   AS without_rules,
               count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM scheme_sources x WHERE x.scheme_id = s.id))
                   AS without_sources,
               (SELECT count(*) FROM eligibility_rules) AS rules,
               (SELECT count(*) FROM scheme_documents) AS documents,
               max(updated_at) AS last_updated
        FROM schemes s""")
    version = await _one("SELECT version, schema_version, imported_at, scheme_count, manifest_hash "
                         "FROM corpus_versions ORDER BY imported_at DESC, id DESC LIMIT 1")
    return {**row, "by_status": by_status, "corpus_version": version}


async def scheme_index() -> Dict[str, Dict[str, Any]]:
    """{scheme_id: {status, needs_review, possible_duplicate, name, official_url}} for every scheme."""
    rows = await _all("SELECT scheme_id, name, status, needs_review, possible_duplicate, official_url, "
                      "review_notes FROM schemes")
    return {r["scheme_id"]: r for r in rows}


async def recent_ingestion_runs(limit: int = 5) -> List[dict]:
    return await _all(
        "SELECT r.id, r.status, r.started_at, r.completed_at, r.records_read, r.records_inserted, "
        "r.records_updated, r.records_skipped, r.errors, v.version AS corpus_version "
        "FROM ingestion_runs r LEFT JOIN corpus_versions v ON v.id = r.corpus_version_id "
        "ORDER BY r.started_at DESC, r.id DESC LIMIT %s", (limit,))


async def rules_by_scheme() -> Dict[str, List[EligibilityRuleRow]]:
    out: Dict[str, List[EligibilityRuleRow]] = {}
    for r in await _all("SELECT s.scheme_id AS sid, e.* FROM eligibility_rules e JOIN schemes s "
                        "ON s.id = e.scheme_id ORDER BY s.scheme_id, e.rule_order"):
        out.setdefault(r.pop("sid"), []).append(EligibilityRuleRow(**r))
    return out


async def integrity_findings() -> Dict[str, List[str]]:
    """Read-only data checks the import's own constraints don't cover."""
    q = {
        "active_without_sources": "SELECT scheme_id FROM schemes s WHERE status = 'ACTIVE' AND NOT EXISTS "
                                  "(SELECT 1 FROM scheme_sources x WHERE x.scheme_id = s.id) ORDER BY 1",
        "active_without_official_url": "SELECT scheme_id FROM schemes WHERE status = 'ACTIVE' AND "
                                       "(official_url IS NULL OR official_url = '') ORDER BY 1",
        "rules_with_unknown_operator": "SELECT DISTINCT s.scheme_id FROM eligibility_rules e JOIN schemes s "
                                       "ON s.id = e.scheme_id WHERE e.operator = 'UNKNOWN' ORDER BY 1",
        "active_without_rules": "SELECT scheme_id FROM schemes s WHERE status = 'ACTIVE' AND NOT EXISTS "
                                "(SELECT 1 FROM eligibility_rules r WHERE r.scheme_id = s.id) ORDER BY 1",
        "flagged_needs_review": "SELECT scheme_id FROM schemes WHERE needs_review ORDER BY 1",
        "flagged_possible_duplicate": "SELECT scheme_id FROM schemes WHERE possible_duplicate ORDER BY 1",
    }
    return {name: [r["scheme_id"] for r in await _all(sql)] for name, sql in q.items()}


# ─── admin jobs ───────────────────────────────────────────────────────────────

def _job(row: Optional[dict]) -> Optional[dict]:
    return {k: row.get(k) for k in JOB_COLUMNS} if row else None


async def create_job(kind: str, dry_run: bool, reason: str, account_pk: Optional[int], label: str,
                     correlation_id: Optional[str], params: Optional[dict] = None) -> dict:
    job_id = str(uuid.uuid4())
    busy = False
    row = None
    async with get_db_connection() as conn:
        try:
            async with conn.transaction():
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute(
                        "INSERT INTO admin_jobs (id, kind, dry_run, reason, requested_by_account_id, requested_by, "
                        "correlation_id, params) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
                        (job_id, kind, dry_run, reason, account_pk, label, correlation_id,
                         Jsonb(params) if params is not None else None))
                    row = await cur.fetchone()
        except pg_errors.UniqueViolation:            # uq_admin_jobs_one_active
            busy = True
    if busy:
        raise JobInProgress()
    return _job(row)


async def get_job(job_id: str) -> Optional[dict]:
    return _job(await _one("SELECT * FROM admin_jobs WHERE id = %s", (job_id,)))


async def active_job() -> Optional[dict]:
    return _job(await _one("SELECT * FROM admin_jobs WHERE status IN ('QUEUED', 'RUNNING') LIMIT 1"))


async def list_jobs(limit: int, offset: int) -> Tuple[List[dict], int]:
    total = (await _one("SELECT count(*) AS n FROM admin_jobs"))["n"]
    rows = await _all("SELECT * FROM admin_jobs ORDER BY created_at DESC LIMIT %s OFFSET %s", (limit, offset))
    return [_job(r) for r in rows], total


async def mark_running(job_id: str) -> bool:
    row = await _one_write("UPDATE admin_jobs SET status = 'RUNNING', started_at = NOW() "
                           "WHERE id = %s AND status = 'QUEUED' RETURNING id", (job_id,))
    return row is not None


async def finish(job_id: str, status: str, result: Optional[dict], error: Optional[str]) -> None:
    await _one_write("UPDATE admin_jobs SET status = %s, finished_at = NOW(), result = %s, error = %s "
                     "WHERE id = %s RETURNING id",
                     (status, Jsonb(result) if result is not None else None, error, job_id))


async def fail_interrupted() -> List[dict]:
    """Queued / running jobs found at startup were interrupted by a restart."""
    rows = await _all_write(
        "UPDATE admin_jobs SET status = 'FAILED', finished_at = NOW(), "
        "error = 'Interrupted: the server stopped while the job was queued or running.' "
        "WHERE status IN ('QUEUED', 'RUNNING') RETURNING *")
    return [_job(r) for r in rows]


async def _all_write(query: str, params: tuple = ()) -> List[dict]:
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()
        await conn.commit()
    return rows


async def _one_write(query: str, params: tuple = ()) -> Optional[dict]:
    rows = await _all_write(query, params)
    return rows[0] if rows else None
