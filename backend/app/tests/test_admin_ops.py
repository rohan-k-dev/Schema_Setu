"""
Administrator operations (docs/ADMIN_OPERATIONS.md) through the HTTP API with real
sessions: the dashboard and its failure isolation, recent errors (redacted, with
correlation ids), validation, conflict inspection, jobs (dry run, confirmation,
one at a time, success / refusal / crash, restart recovery), a real graph rebuild
with staging + backup + automatic restore, audit-log integrity (hash chain), input
validation and redaction of sensitive data. Who may call what is in test_rbac.py.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone

import pytest

from app.core import error_buffer, request_context
from app.core.audit_chain import GENESIS, entry_hash, verify
from app.core.config import settings
from app.core.redaction import redact, sanitize
from app.models.review import ReviewReason
from app.services import admin_jobs
from app.services import knowledge_graph_service as kg
from app.services import review_service
from app.tests.test_rbac import env  # noqa: F401  (fixture)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
REAL_GRAPH = os.path.join(ROOT, "data", "graph", "current")


@pytest.fixture
def admin(env, monkeypatch):  # noqa: F811
    monkeypatch.setattr("app.services.ops_service.is_db_available", lambda: True)    # the fake ops store
    env.user("ADMIN")                          # a second admin, so tests can change the first
    return env.user("ADMIN")


@pytest.fixture(autouse=True)
def _clean_errors():
    error_buffer.buffer.clear()
    yield
    error_buffer.buffer.clear()


def job(admin, body, **headers):
    return admin.call("POST", "/admin/ops/jobs", body, headers=headers or None)


# ─── dashboard ────────────────────────────────────────────────────────────────

class TestDashboard:
    def test_overview_has_every_section(self, env, admin):
        body = admin.call("GET", "/admin/ops/overview").json()
        for name in ("system", "corpus", "ingestion", "graph", "reviews", "errors"):
            assert name in body, name
        assert body["system"]["status"] == "OK" and body["system"]["database"]["migration"] == "0007"
        assert body["corpus"]["file"]["schemes"] == 40
        assert body["reviews"]["status"] == "OK" and body["ingestion"]["recent_jobs"] == []

    def test_one_failing_source_doesnt_blank_the_dashboard(self, env, admin):
        env.ops.down = True
        r = admin.call("GET", "/admin/ops/overview")
        assert r.status_code == 200
        body = r.json()
        assert body["corpus"]["status"] == "UNAVAILABLE" and body["ingestion"]["status"] == "UNAVAILABLE"
        assert body["reviews"]["status"] == "OK" and body["errors"]["status"] == "OK"
        assert "database down" not in r.text                     # no internal detail in the page

    def test_no_secret_values_in_the_dashboard(self, env, admin, monkeypatch):
        monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_live_SECRETVALUE1234567890")
        r = admin.call("GET", "/admin/ops/overview")
        assert "SECRETVALUE" not in r.text and r.json()["system"]["external_services"]["groq"] is True

    def test_migration_drift_is_flagged(self, env, admin):
        env.ops.version = "0005"
        warnings = admin.call("GET", "/admin/ops/overview").json()["system"]["warnings"]
        assert any("alembic upgrade head" in w for w in warnings)

    def test_pending_reviews_and_source_conflicts(self, env, admin):
        review_service.create_review_case("s1", "q", ReviewReason.SOURCE_CONFLICT, {"state": "KA"}, ["PM_KISAN"],
                                          [], [{"scheme_id": "PM_KISAN", "field": "official_url",
                                                "values": {"database": "https://pmkisan.gov.in",
                                                           "live_web": "https://evil.example/" + "x" * 400}}])
        reviews = admin.call("GET", "/admin/ops/overview").json()["reviews"]
        assert reviews["open_by_reason"] == {"SOURCE_CONFLICT": 1} and reviews["with_source_conflicts"] == 1
        c = admin.call("GET", "/admin/ops/conflicts").json()
        assert c["source_conflicts_total"] == 1 and len(c["source_conflicts"][0]["values"]["live_web"]) <= 300
        assert c["rule_conflicts"][0]["type"] == "CONTRADICTORY_BOUNDS"
        assert c["flagged_schemes"][0]["scheme_id"] == "OLD" and "a@b.com" not in json.dumps(c)


# ─── errors and correlation ids ───────────────────────────────────────────────

class TestErrorsAndCorrelation:
    def test_errors_are_redacted_and_carry_the_request_id(self, env, admin):
        token = request_context.bind("req-abc-12345678")
        try:
            logging.getLogger("app.test").error(
                "boom password=hunter2 for ramesh@example.com key gsk_abcdefghijklmnop1234 "
                "aadhaar 1234 5678 9012 phone 9876543210 db postgresql://u:pw@host/db "
                "cookie ss_session=AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-")
        finally:
            request_context.reset(token)
        row = admin.call("GET", "/admin/ops/errors").json()["items"][0]
        for secret in ("hunter2", "ramesh@example.com", "gsk_abcdefghijklmnop1234", "1234 5678 9012",
                       "9876543210", "u:pw@", "AbCdEfGhIjKlMnOpQrStUvWxYz"):
            assert secret not in row["message"], secret
        assert row["correlation_id"] == "req-abc-12345678" and row["level"] == "ERROR"

    def test_request_id_is_echoed_or_replaced(self, env, admin):
        r = admin.c.get("/admin/ops/overview", headers={"X-Request-ID": "trace-0001-abcd"})
        assert r.headers["X-Request-ID"] == "trace-0001-abcd"
        bad = admin.c.get("/admin/ops/overview", headers={"X-Request-ID": "bad id\nInjected: x"})
        assert bad.headers["X-Request-ID"] != "bad id\nInjected: x" and len(bad.headers["X-Request-ID"]) == 32

    def test_audit_event_has_the_requests_correlation_id(self, env, admin):
        r = admin.call("POST", "/admin/ops/validate", headers={"X-Request-ID": "corr-validate-01"})
        assert r.status_code == 200
        event = env.audit.rows[-1]
        assert (event.action, event.correlation_id, event.actor_label) == (
            "VALIDATION_RUN", "corr-validate-01", admin.email)
        found = admin.call("GET", "/admin/audit-events?correlation_id=corr-validate-01").json()
        assert found["total"] == 1

    def test_errors_pagination_and_limits(self, env, admin):
        for i in range(30):
            logging.getLogger("app.test").error(f"error {i}")
        page = admin.call("GET", "/admin/ops/errors?limit=10&offset=5").json()
        assert page["total"] == 30 and len(page["items"]) == 10 and page["items"][0]["message"] == "error 24"
        assert admin.call("GET", "/admin/ops/errors?limit=1000").status_code == 422


# ─── validation ───────────────────────────────────────────────────────────────

class TestValidation:
    def test_report_covers_file_database_drift_and_graph(self, env, admin):
        body = admin.call("POST", "/admin/ops/validate").json()
        names = {c["name"]: c["status"] for c in body["checks"]}
        assert set(names) >= {"corpus_file", "rule_conflicts", "database_integrity", "curation_flags",
                              "file_vs_database", "knowledge_graph"}
        # the real corpus file: 0 errors, but warnings (e.g. missing optional fields) → WARN
        assert names["corpus_file"] == "WARN" and names["rule_conflicts"] == "FAIL"   # fake has 2 contradicting rules
        assert names["file_vs_database"] == "FAIL"                                  # fake DB has 2 of 40 schemes
        assert body["overall"] == "FAIL" and env.audit.rows[-1].outcome == "FAILURE"

    def test_database_outage_is_reported_not_crashed(self, env, admin):
        env.ops.down = True
        body = admin.call("POST", "/admin/ops/validate").json()
        statuses = {c["name"]: c["status"] for c in body["checks"]}
        assert statuses["database"] == "ERROR" and body["overall"] == "ERROR"
        assert statuses["corpus_file"] == "WARN"                         # the file check still ran

    def test_validation_changes_nothing(self, env, admin):
        before = json.dumps(env.ops.schemes, sort_keys=True)
        admin.call("POST", "/admin/ops/validate")
        assert json.dumps(env.ops.schemes, sort_keys=True) == before and env.ops.jobs == {}


# ─── jobs ─────────────────────────────────────────────────────────────────────

class TestJobs:
    def test_dry_run_is_the_default_and_reports_a_plan(self, env, admin, monkeypatch):
        called = []

        async def no_import(**kw):
            called.append(kw)
        monkeypatch.setattr("app.services.corpus_import_service.import_corpus", no_import)
        r = job(admin, {"kind": "IMPORT_CORPUS", "reason": "check before import"})
        assert r.status_code == 202 and r.json()["dry_run"] is True
        done = admin.call("GET", f"/admin/ops/jobs/{r.json()['id']}").json()
        assert done["status"] == "SUCCEEDED" and called == []
        plan = done["result"]["plan"]
        # fake DB: PM_KISAN (in the file) + OLD (not in the file, kept: the importer never deletes)
        assert len(plan["to_insert"]) == 39 and plan["to_update"] == 1
        assert plan["kept_not_in_file"] == ["OLD"]
        actions = [(e.action, e.outcome) for e in env.audit.rows]
        assert ("JOB_REQUESTED", "SUCCESS") in actions and ("JOB_SUCCEEDED", "SUCCESS") in actions

    @pytest.mark.parametrize("confirm", [None, "", "yes", "REBUILD_GRAPH"])
    def test_real_run_needs_the_exact_confirmation(self, env, admin, confirm):
        body = {"kind": "IMPORT_CORPUS", "dry_run": False, "reason": "import the new corpus"}
        if confirm is not None:
            body["confirm"] = confirm
        r = job(admin, body)
        assert r.status_code == 422 and env.ops.jobs == {}
        if confirm not in ("",):
            assert r.json()["detail"]["code"] == "CONFIRM_REQUIRED"
            assert env.audit.rows[-1].outcome == "FAILURE"

    def test_real_import_runs_the_transactional_importer(self, env, admin, monkeypatch):
        class Stats:
            def to_dict(self):
                return {"records_read": 40, "records_inserted": 38, "records_updated": 2, "errors": 0}

        async def fake_import(**kw):
            assert kw == {"dry_run": False, "force": False}           # never the partial "force" mode
            return Stats()
        monkeypatch.setattr("app.services.corpus_import_service.import_corpus", fake_import)
        r = job(admin, {"kind": "IMPORT_CORPUS", "dry_run": False, "confirm": "IMPORT_CORPUS",
                        "reason": "import the new corpus"})
        done = env.ops.jobs[r.json()["id"]]
        assert done["status"] == "SUCCEEDED" and done["result"]["import"]["records_inserted"] == 38

    def test_one_job_at_a_time(self, env, admin):
        env.ops.jobs["x"] = {"id": "x", "kind": "REBUILD_GRAPH", "status": "RUNNING",
                             "created_at": datetime.now(timezone.utc)}
        r = job(admin, {"kind": "REBUILD_GRAPH", "reason": "another one"})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "JOB_IN_PROGRESS"
        assert env.audit.rows[-1].details["refused"] == "JOB_IN_PROGRESS"

    @pytest.mark.parametrize("body", [
        {"kind": "DROP_TABLES", "reason": "please"},
        {"kind": "IMPORT_CORPUS"},                                      # reason required
        {"kind": "IMPORT_CORPUS", "reason": "abc"},                     # too short
        {"kind": "IMPORT_CORPUS", "reason": "x" * 301},
        {"kind": "IMPORT_CORPUS", "reason": "valid reason", "dry_run": "no"},
        {"kind": "IMPORT_CORPUS", "reason": "valid reason", "force": True},
        {"kind": "IMPORT_CORPUS", "reason": "valid reason", "corpus_path": "/etc/passwd"},
    ])
    def test_invalid_job_requests_are_rejected(self, env, admin, body):
        assert job(admin, body).status_code == 422 and env.ops.jobs == {}

    def test_corpus_that_fails_validation_is_never_imported(self, env, admin, monkeypatch):
        monkeypatch.setattr(admin_jobs, "validate_corpus_data",
                            lambda s: {"total": 40, "errors": 3, "warnings": 0, "duplicates": 0, "issues": []})

        async def must_not_run(**kw):
            raise AssertionError("import must not start")
        monkeypatch.setattr("app.services.corpus_import_service.import_corpus", must_not_run)
        r = job(admin, {"kind": "IMPORT_CORPUS", "dry_run": False, "confirm": "IMPORT_CORPUS",
                        "reason": "import the new corpus"})
        done = env.ops.jobs[r.json()["id"]]
        assert done["status"] == "FAILED" and "3 validation error" in done["error"]
        assert env.audit.rows[-1].action == "JOB_FAILED" and env.audit.rows[-1].outcome == "FAILURE"

    def test_crash_is_recorded_without_leaking_details(self, env, admin, monkeypatch):
        async def crash(**kw):
            raise RuntimeError("connection to postgresql://admin:SuperSecret@db failed")
        monkeypatch.setattr("app.services.corpus_import_service.import_corpus", crash)
        r = job(admin, {"kind": "IMPORT_CORPUS", "dry_run": False, "confirm": "IMPORT_CORPUS",
                        "reason": "import the new corpus"}, **{"X-Request-ID": "corr-crash-001"})
        done = env.ops.jobs[r.json()["id"]]
        assert done["status"] == "FAILED" and "SuperSecret" not in done["error"] and "corr-crash-001" in done["error"]
        err = admin.call("GET", "/admin/ops/errors").json()["items"][0]
        assert err["correlation_id"] == "corr-crash-001" and "SuperSecret" not in err["message"]
        assert "SuperSecret" not in json.dumps([e.model_dump(mode="json") for e in env.audit.rows])

    @pytest.mark.asyncio
    async def test_interrupted_jobs_are_failed_at_startup(self, env, monkeypatch):
        monkeypatch.setattr("app.database.connection.is_db_available", lambda: True)
        env.ops.jobs["y"] = {"id": "y", "kind": "IMPORT_CORPUS", "status": "RUNNING",
                             "created_at": datetime.now(timezone.utc)}
        failed = await admin_jobs.fail_interrupted_jobs()
        assert [j["id"] for j in failed] == ["y"] and env.ops.jobs["y"]["status"] == "FAILED"
        assert env.audit.rows[-1].actor_label == "system" and env.audit.rows[-1].action == "JOB_FAILED"


# ─── graph rebuild (real builder, temporary graph folder) ─────────────────────

@pytest.fixture
def graph_dir(tmp_path, monkeypatch):
    base = tmp_path / "graph"
    shutil.copytree(REAL_GRAPH, base / "current")
    monkeypatch.setattr("app.knowledge_graph.serializer._graph_data_dir", lambda: str(base))
    for name in ("_graph_repo", "_graph_available", "_graph_stale"):      # restored after the test
        monkeypatch.setattr(kg, name, getattr(kg, name))
    assert kg.init_knowledge_graph()
    return base


class TestGraphRebuild:
    def test_dry_run_changes_nothing(self, env, admin, graph_dir):
        before = (graph_dir / "current" / "graph.json").read_bytes()
        r = job(admin, {"kind": "REBUILD_GRAPH", "reason": "check the graph"})
        done = env.ops.jobs[r.json()["id"]]
        assert done["status"] == "SUCCEEDED" and done["result"]["nodes"] > 100
        assert (graph_dir / "current" / "graph.json").read_bytes() == before
        assert not (graph_dir / "backups").exists()

    def test_real_rebuild_swaps_in_keeps_a_backup_and_reloads(self, env, admin, graph_dir):
        r = job(admin, {"kind": "REBUILD_GRAPH", "dry_run": False, "confirm": "REBUILD_GRAPH",
                        "reason": "rebuild after corpus update"})
        done = env.ops.jobs[r.json()["id"]]
        assert done["status"] == "SUCCEEDED", done["error"]
        backups = list((graph_dir / "backups").iterdir())
        assert len(backups) == 1 and (backups[0] / "graph.json").exists()
        assert not any(p.name.startswith(".staging") for p in graph_dir.iterdir())
        assert done["result"]["loaded"]["loaded"] is True and kg.is_graph_available()
        meta = json.loads((graph_dir / "current" / "metadata.json").read_text())
        assert meta["graph_hash"] == done["result"]["graph_hash"]

    def test_rebuild_works_where_directories_cant_be_renamed(self, env, admin, graph_dir, monkeypatch):
        """Regression: in Docker (overlayfs) renaming an image directory fails with EXDEV."""
        import errno
        real_replace = os.replace

        def overlay_replace(src, dst):
            if os.path.isdir(src):
                raise OSError(errno.EXDEV, "Invalid cross-device link")
            return real_replace(src, dst)
        monkeypatch.setattr("app.services.admin_jobs.os.replace", overlay_replace)
        r = job(admin, {"kind": "REBUILD_GRAPH", "dry_run": False, "confirm": "REBUILD_GRAPH",
                        "reason": "rebuild after corpus update"})
        done = env.ops.jobs[r.json()["id"]]
        assert done["status"] == "SUCCEEDED", done["error"]
        assert (graph_dir / "current" / "graph.json").exists() and kg.is_graph_available()

    def test_failed_reload_restores_the_previous_graph(self, env, admin, graph_dir, monkeypatch):
        before = (graph_dir / "current" / "graph.json").read_bytes()
        real_init = kg.init_knowledge_graph
        calls = []

        def flaky():
            calls.append(1)
            return False if len(calls) == 1 else real_init()
        monkeypatch.setattr(kg, "init_knowledge_graph", flaky)
        r = job(admin, {"kind": "REBUILD_GRAPH", "dry_run": False, "confirm": "REBUILD_GRAPH",
                        "reason": "rebuild after corpus update"})
        done = env.ops.jobs[r.json()["id"]]
        assert done["status"] == "FAILED" and "previous graph was restored" in done["error"]
        assert (graph_dir / "current" / "graph.json").read_bytes() == before and kg.is_graph_available()

    def test_invalid_graph_is_never_swapped_in(self, env, admin, graph_dir, monkeypatch):
        class Bad:
            is_valid = False
            errors = ["dangling edge SCHEME:X -> STATE:Y"]
            warnings = []
        monkeypatch.setattr(admin_jobs, "_build_graph", lambda s, v: (None, {}, Bad()))
        before = (graph_dir / "current" / "graph.json").read_bytes()
        r = job(admin, {"kind": "REBUILD_GRAPH", "dry_run": False, "confirm": "REBUILD_GRAPH",
                        "reason": "rebuild after corpus update"})
        done = env.ops.jobs[r.json()["id"]]
        assert done["status"] == "FAILED" and "failed validation" in done["error"]
        assert (graph_dir / "current" / "graph.json").read_bytes() == before


# ─── audit log ────────────────────────────────────────────────────────────────

class TestAuditIntegrity:
    def test_every_sensitive_action_has_the_required_fields(self, env, admin):
        f = env.user("FARMER")
        admin.call("PATCH", f"/admin/users/{f.farmer_id}/role", {"role": "REVIEWER"},
                   headers={"X-Request-ID": "corr-role-0001"})
        e = next(x for x in env.audit.rows if x.action == "ROLE_CHANGED")
        assert e.actor_label == admin.email and e.actor_role == "ADMIN" and e.target_id == f.farmer_id
        assert e.outcome == "SUCCESS" and e.correlation_id == "corr-role-0001" and e.occurred_at
        api = admin.call("GET", "/admin/audit-events?action=ROLE_CHANGED").json()["items"][0]
        assert {"actor_label", "action", "target_type", "target_id", "occurred_at", "outcome",
                "correlation_id"} <= set(api)

    def test_refused_and_denied_actions_are_audited_with_their_outcome(self, env, admin):
        admin.call("PATCH", f"/admin/users/{admin.farmer_id}/role", {"role": "FARMER"})
        f = env.user("FARMER")
        f.call("POST", "/admin/ops/validate")
        outcomes = {(e.action, e.outcome) for e in env.audit.rows}
        assert ("ROLE_CHANGED", "FAILURE") in outcomes and ("ACCESS_DENIED", "DENIED") in outcomes
        assert admin.call("GET", "/admin/audit-events?outcome=DENIED").json()["total"] >= 1

    def test_chain_verifies_and_detects_tampering(self, env, admin):
        admin.call("POST", "/admin/ops/validate")
        admin.call("POST", "/admin/ops/validate")
        ok = admin.call("GET", "/admin/audit-events/verify").json()
        assert ok["valid"] is True and ok["checked"] == 2
        env.audit.rows[0] = env.audit.rows[0].model_copy(update={"actor_label": "someone-else"})
        bad = admin.call("GET", "/admin/audit-events/verify").json()
        assert bad["valid"] is False and bad["first_broken_id"] == 1 and "modified" in bad["reason"]
        assert env.audit.rows[-1].action == "AUDIT_VERIFIED" and env.audit.rows[-1].outcome == "FAILURE"

    def test_chain_detects_a_removed_event(self):
        rows, prev = [], GENESIS
        for i in range(1, 4):
            r = {"id": i, "occurred_at": datetime(2026, 1, i, tzinfo=timezone.utc), "action": "X",
                 "actor_label": "a", "outcome": "SUCCESS"}
            r["prev_hash"], r["entry_hash"] = prev, entry_hash(prev, r)
            prev = r["entry_hash"]
            rows.append(r)
        assert verify(rows)["valid"]
        result = verify([rows[0], rows[2]])
        assert result == {"valid": False, "checked": 2, "first_broken_id": 3,
                          "reason": result["reason"]} and "removed" in result["reason"]

    @pytest.mark.parametrize("query", ["limit=500", "limit=0", "offset=-1", "outcome=MAYBE", "action=drop table",
                                       "correlation_id=a%20b", "since=2026-02-01T00:00:00Z&until=2026-01-01T00:00:00Z"])
    def test_audit_queries_are_validated(self, env, admin, query):
        assert admin.call("GET", f"/admin/audit-events?{query}").status_code == 422

    def test_audit_pagination_and_time_window(self, env, admin):
        for _ in range(7):
            admin.call("POST", "/admin/ops/validate")
        p1 = admin.call("GET", "/admin/audit-events?action=VALIDATION_RUN&limit=3").json()
        p3 = admin.call("GET", "/admin/audit-events?action=VALIDATION_RUN&limit=3&offset=6").json()
        assert p1["total"] == 7 and len(p1["items"]) == 3 and len(p3["items"]) == 1
        assert p1["items"][0]["id"] > p1["items"][1]["id"]                  # newest first
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat().replace("+00:00", "Z")
        assert admin.call("GET", f"/admin/audit-events?since={future}").json()["total"] == 0


def test_manifest_version_is_read_from_corpus_version_key():
    """Regression: importer and graph build read manifest["version"], but the key is corpus_version."""
    from app.services.corpus_import_service import load_corpus, manifest_version
    _, manifest = load_corpus()
    assert "corpus_version" in manifest and manifest_version(manifest) == manifest["corpus_version"]
    assert manifest_version({"corpus_version": "1.1.0"}) == "1.1.0"
    assert manifest_version({"version": "0.9.0"}) == "0.9.0" and manifest_version({}) == "1.0.0"


# ─── redaction ────────────────────────────────────────────────────────────────

class TestRedaction:
    def test_sensitive_keys_and_values_never_reach_audit_details(self, env, admin):
        details = sanitize({"password": "hunter2", "api_key": "gsk_x", "session_token": "abc", "phone": "98765",
                            "profile": {"state": "KA"}, "note": "mail me at x@y.org", "reason": "ok",
                            "job_id": "0b9c2d5e-1f2a-4b3c-8d9e-0f1a2b3c4d5e"})
        assert details["password"] == details["api_key"] == details["session_token"] == "[redacted]"
        assert details["phone"] == details["profile"] == "[redacted]"
        assert details["note"] == "mail me at [email]" and details["reason"] == "ok"
        assert details["job_id"] == "0b9c2d5e-1f2a-4b3c-8d9e-0f1a2b3c4d5e"       # ids stay readable

    def test_no_raw_session_or_csrf_values_in_audit_or_errors(self, env, admin):
        admin.call("POST", "/admin/ops/validate")
        logging.getLogger("app.test").error(f"session {admin.c.cookies['ss_session']}")
        stored = json.dumps([e.model_dump(mode="json") for e in env.audit.rows]) + json.dumps(
            admin.call("GET", "/admin/ops/errors").json())
        assert admin.c.cookies["ss_session"] not in stored and admin.csrf not in stored

    @pytest.mark.parametrize("text,leak", [
        ("Authorization: Bearer abc.def.ghi", "abc.def.ghi"),
        ("password: 's3cret!'", "s3cret!"),
        ("tvly-AbCdEfGhIjKl12345", "AbCdEfGhIjKl12345"),
        ("+91 9876543210", "9876543210"),
    ])
    def test_redact_patterns(self, text, leak):
        assert leak not in redact(text)
