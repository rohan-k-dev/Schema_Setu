"""
Integration tests: admin operations against PostgreSQL — migration 0007 (outcome +
hash-chain backfill of existing events), the real audit chain (concurrent writers,
tampering by someone who bypasses the append-only trigger, a deleted event), the
one-active-job index, interrupted-job recovery, and a real corpus import job followed
by validation and graph-sync status.

Opt-in, like test_auth_repository_pg.py (throw-away database; tables are truncated):
    TEST_DATABASE_URL=postgresql://schemesetu:schemesetu@localhost:5432/schemesetu_auth_test \
        python -m pytest app/tests/test_admin_ops_pg.py
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.permissions import Principal, Role, permissions_for
from app.tests.test_auth_repository_pg import TEST_URL, _alembic
from app.tests.test_rbac_pg import run as _run

pytestmark = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL not set (PostgreSQL integration)")

ADMIN = Principal(role=Role.ADMIN, label="ops-admin@example.com", account_pk=None, farmer_id=None,
                  permissions=permissions_for(Role.ADMIN))


@pytest.fixture(scope="module", autouse=True)
def migrated_db():
    _alembic("upgrade", "head")
    yield


def run(factory, truncate: bool = True):
    async def body():
        if truncate:
            from app.database.connection import get_db_connection
            async with get_db_connection() as conn:
                if (await (await conn.execute("SELECT to_regclass('admin_jobs')")).fetchone())[0]:
                    await conn.execute("TRUNCATE admin_jobs")
        return await factory()
    return _run(body, truncate)


async def _exec(q, params=()):
    from app.database.connection import get_db_connection
    async with get_db_connection() as conn:
        await conn.execute(q, params)
        await conn.commit()


async def _scalar(q, params=()):
    from app.database.connection import get_db_connection
    async with get_db_connection() as conn:
        return (await (await conn.execute(q, params)).fetchone())[0]


def test_migration_chains_existing_events_and_sets_outcomes():
    _alembic("downgrade", "0006")

    async def old_events():
        for action in ("ROLE_CHANGED", "ACCESS_DENIED", "SCHEME_CURATED"):
            await _exec("INSERT INTO audit_events (actor_label, action, details) VALUES ('old@x', %s, '{\"k\": 1}')",
                        (action,))
    try:
        run(old_events)
    finally:
        _alembic("upgrade", "head")

    async def check():
        from app.database.repositories import audit_repository as audit
        outcomes = await _scalar("SELECT array_agg(outcome ORDER BY id) FROM audit_events")
        await audit.record(ADMIN, "AFTER_MIGRATION", "x", "1")          # continues the backfilled chain
        return outcomes, await audit.verify_chain()
    outcomes, result = run(check, truncate=False)
    assert outcomes == ["SUCCESS", "DENIED", "SUCCESS"]
    assert result["valid"] and result["checked"] == 4


def test_concurrent_writers_keep_one_valid_chain():
    async def body():
        from app.database.repositories import audit_repository as audit
        await asyncio.gather(*[audit.record(ADMIN, "CONCURRENT", "n", str(i), {"i": i}) for i in range(20)])
        return await audit.verify_chain(batch=7), await _scalar("SELECT count(DISTINCT prev_hash) FROM audit_events")
    result, distinct_prev = run(body)
    assert result["valid"] and result["checked"] == 20 and distinct_prev == 20


def test_tampering_that_bypasses_the_trigger_is_detected():
    async def body():
        from app.database.repositories import audit_repository as audit
        for i in range(5):
            await audit.record(ADMIN, "EVENT", "n", str(i), outcome="SUCCESS")
        blocked = None
        try:
            await _exec("UPDATE audit_events SET outcome = 'FAILURE'")
        except Exception as exc:
            blocked = "append-only" in str(exc)
        third = await _scalar("SELECT id FROM audit_events ORDER BY id OFFSET 2 LIMIT 1")
        # a database owner can bypass the trigger — the chain still shows it
        await _exec("ALTER TABLE audit_events DISABLE TRIGGER trg_audit_events_append_only")
        try:
            await _exec("UPDATE audit_events SET actor_label = 'nobody' WHERE id = %s", (third,))
            modified = await audit.verify_chain()
            fourth = await _scalar("SELECT id FROM audit_events ORDER BY id OFFSET 3 LIMIT 1")
            await _exec("DELETE FROM audit_events WHERE id = %s", (fourth,))
            removed = await audit.verify_chain()
        finally:
            await _exec("ALTER TABLE audit_events ENABLE TRIGGER trg_audit_events_append_only")
        return blocked, third, modified, removed
    blocked, third, modified, removed = run(body)
    assert blocked is True
    assert not modified["valid"] and modified["first_broken_id"] == third and "modified" in modified["reason"]
    assert not removed["valid"] and removed["first_broken_id"] == third       # still the first broken one


def test_outcome_is_constrained_and_details_are_sanitised():
    async def body():
        from app.database.repositories import audit_repository as audit
        await audit.record(ADMIN, "SANITISED", "x", "1", {"password": "hunter2", "note": "call 9876543210"})
        details = await _scalar("SELECT details FROM audit_events WHERE action = 'SANITISED'")
        try:
            await _exec("INSERT INTO audit_events (actor_label, action, outcome, prev_hash, entry_hash) "
                        "VALUES ('x', 'X', 'MAYBE', 'p', 'h')")
            constrained = False
        except Exception:
            constrained = True
        return details, constrained
    details, constrained = run(body)
    assert details == {"password": "[redacted]", "note": "call [phone]"} and constrained


def test_only_one_active_job_and_interrupted_jobs_fail():
    async def body():
        from app.database.repositories import ops_repository as ops
        first = await ops.create_job("REBUILD_GRAPH", True, "first", None, "a", "c1")
        try:
            await ops.create_job("IMPORT_CORPUS", True, "second", None, "a", "c2")
            second = "created"
        except ops.JobInProgress:
            second = "refused"
        await ops.mark_running(first["id"])
        interrupted = await ops.fail_interrupted()
        third = await ops.create_job("IMPORT_CORPUS", True, "after recovery", None, "a", "c3")
        return second, [j["id"] for j in interrupted], first["id"], third["status"]
    second, interrupted, first_id, third = run(body)
    assert second == "refused" and interrupted == [first_id] and third == "QUEUED"


def test_real_import_job_then_validation_and_graph_sync():
    async def body():
        from app.services import admin_jobs, ops_service
        from app.services.knowledge_graph_service import init_knowledge_graph
        init_knowledge_graph()                                            # the repository's real graph (read-only)
        dry = await admin_jobs.run_import(dry_run=True)
        n_before = await _scalar("SELECT count(*) FROM schemes")
        real = await admin_jobs.run_import(dry_run=False)
        n_after = await _scalar("SELECT count(*) FROM schemes")
        runs = await _scalar("SELECT array_agg(status) FROM ingestion_runs")
        again = await admin_jobs.run_import(dry_run=True)
        report = await ops_service.validate(ADMIN)
        return dry, n_before, real, n_after, runs, again, report
    dry, n_before, real, n_after, runs, again, report = run(body)
    assert n_before == 0 and len(dry["plan"]["to_insert"]) == 40              # dry run changed nothing
    assert n_after == 40 and real["import"]["records_inserted"] == 40 and "SUCCESS" in runs
    assert again["plan"]["to_insert"] == [] and again["plan"]["to_update"] == 40   # idempotent
    checks = {c["name"]: c["status"] for c in report["checks"]}
    assert checks["file_vs_database"] in ("PASS", "WARN") and checks["corpus_file"] in ("PASS", "WARN")
    assert real["graph_sync"]["loaded"] is True and real["graph_sync"]["schemes_missing_from_graph"] == []
