"""
In-memory stand-ins for audit_repository (hash-chained, like the real one) and
ops_repository, so the admin and operations flows can be tested through the HTTP API
without PostgreSQL. test_admin_ops_pg.py runs the real SQL.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from app.core import request_context
from app.core.audit_chain import GENESIS, entry_hash, verify
from app.core.redaction import sanitize
from app.database.repositories.ops_repository import JobInProgress
from app.models.db import EligibilityRuleRow
from app.models.db.farmer_auth import AuditEventRow


class FakeAudit:
    """audit_repository: append-only, hash-chained list (same fields and sanitising)."""

    def __init__(self):
        self.rows: list[AuditEventRow] = []

    def add(self, actor, action, target_type=None, target_id=None, details=None, outcome="SUCCESS",
            correlation_id=None):
        assert outcome in ("SUCCESS", "FAILURE", "DENIED")
        e = {
            "id": len(self.rows) + 1, "occurred_at": datetime.now(timezone.utc),
            "actor_account_id": actor.account_pk, "actor_label": actor.label,
            "actor_role": actor.role.value if actor.role else None, "action": action,
            "target_type": target_type, "target_id": target_id,
            "details": sanitize(details) if details is not None else None, "ip_address": actor.ip_address,
            "outcome": outcome, "correlation_id": correlation_id or request_context.current(),
        }
        e["prev_hash"] = self.rows[-1].entry_hash if self.rows else GENESIS
        e["entry_hash"] = entry_hash(e["prev_hash"], e)
        self.rows.append(AuditEventRow(**e))

    async def record(self, actor, action, target_type=None, target_id=None, details=None, outcome="SUCCESS",
                     correlation_id=None):
        self.add(actor, action, target_type, target_id, details, outcome, correlation_id)

    async def list_page(self, limit, offset, action=None, target_type=None, target_id=None, actor=None,
                        outcome=None, correlation_id=None, since=None, until=None):
        def keep(r):
            return all(v is None or getattr(r, f) == v for f, v in (
                ("action", action), ("target_type", target_type), ("target_id", target_id),
                ("actor_label", actor), ("outcome", outcome), ("correlation_id", correlation_id))) and \
                (since is None or r.occurred_at >= since) and (until is None or r.occurred_at < until)
        rows = [r for r in reversed(self.rows) if keep(r)]
        return rows[offset:offset + limit], len(rows)

    async def verify_chain(self):
        return verify(r.model_dump() for r in self.rows)


class FakeOpsRepo:
    """ops_repository: corpus status from fixed values, jobs with the one-active rule."""

    JobInProgress = JobInProgress

    def __init__(self):
        self.down = False
        self.schemes = {
            "PM_KISAN": {"scheme_id": "PM_KISAN", "name": "PM-KISAN", "status": "ACTIVE", "needs_review": False,
                         "possible_duplicate": False, "official_url": "https://pmkisan.gov.in", "review_notes": None},
            "OLD": {"scheme_id": "OLD", "name": "Old scheme", "status": "SUSPENDED", "needs_review": True,
                    "possible_duplicate": False, "official_url": None, "review_notes": "check amount, a@b.com"},
        }
        self.rules = {"PM_KISAN": [
            EligibilityRuleRow(id=1, scheme_id=1, field_name="land_size_acres", operator="LTE", value_json=2),
            EligibilityRuleRow(id=2, scheme_id=1, field_name="land_size_acres", operator="GTE", value_json=5),
        ]}
        self.jobs: dict[str, dict] = {}
        self.version = "0007"

    def _check(self):
        if self.down:
            raise RuntimeError("database down")

    async def migration_version(self):
        self._check()
        return self.version

    async def corpus_stats(self):
        self._check()
        return {"schemes": len(self.schemes), "needs_review": 1, "possible_duplicates": 0, "without_rules": 1,
                "without_sources": 0, "rules": 2, "documents": 3, "last_updated": None,
                "by_status": {"ACTIVE": 1, "SUSPENDED": 1},
                "corpus_version": {"version": "1.0.0", "schema_version": "1.0.0", "imported_at": None,
                                   "scheme_count": 2, "manifest_hash": "abc"}}

    async def scheme_index(self):
        self._check()
        return dict(self.schemes)

    async def recent_ingestion_runs(self, limit=5):
        self._check()
        return []

    async def rules_by_scheme(self):
        self._check()
        return dict(self.rules)

    async def integrity_findings(self):
        self._check()
        return {"active_without_sources": [], "active_without_official_url": [], "rules_with_unknown_operator": [],
                "active_without_rules": [], "flagged_needs_review": ["OLD"], "flagged_possible_duplicate": []}

    async def create_job(self, kind, dry_run, reason, account_pk, label, correlation_id, params=None):
        self._check()
        if any(j["status"] in ("QUEUED", "RUNNING") for j in self.jobs.values()):
            raise JobInProgress()
        job = {"id": str(uuid.uuid4()), "kind": kind, "status": "QUEUED", "dry_run": dry_run, "reason": reason,
               "requested_by": label, "correlation_id": correlation_id, "created_at": datetime.now(timezone.utc),
               "started_at": None, "finished_at": None, "result": None, "error": None, "params": params}
        self.jobs[job["id"]] = job
        return dict(job)

    async def get_job(self, job_id):
        j = self.jobs.get(job_id)
        return dict(j) if j else None

    async def active_job(self):
        return next((dict(j) for j in self.jobs.values() if j["status"] in ("QUEUED", "RUNNING")), None)

    async def list_jobs(self, limit, offset):
        self._check()
        rows = sorted(self.jobs.values(), key=lambda j: j["created_at"], reverse=True)
        return [dict(j) for j in rows[offset:offset + limit]], len(rows)

    async def mark_running(self, job_id):
        j = self.jobs.get(job_id)
        if not j or j["status"] != "QUEUED":
            return False
        j.update(status="RUNNING", started_at=datetime.now(timezone.utc))
        return True

    async def finish(self, job_id, status, result, error: Optional[str]):
        self.jobs[job_id].update(status=status, result=result, error=error, finished_at=datetime.now(timezone.utc))

    async def fail_interrupted(self):
        out = []
        for j in self.jobs.values():
            if j["status"] in ("QUEUED", "RUNNING"):
                j.update(status="FAILED", error="Interrupted: the server stopped while the job was queued or running.")
                out.append(dict(j))
        return out
