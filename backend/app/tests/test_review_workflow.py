"""
Reviewer dashboard (docs/HUMAN_REVIEW.md): the queue and its filters, every workflow
transition, assignment, comments, concurrency (versions, simultaneous claims), the audit
trail, the separation between human decisions and automated results, and what farmers see —
through the real HTTP API with real cookie sessions (in-memory stores; the SQL is covered by
test_review_pg.py). Cases are built from real eligibility-engine results.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.permissions import Principal, permissions_for
from app.core.rate_limit import limiter
from app.eligibility.evaluator import evaluate_scheme
from app.models.db import EligibilityRuleRow
from app.services import review_service
from app.services import review_workflow as wf
from app.tests.fake_auth_repo import FakeAuthRepo
from app.tests.test_profile_module import FakeProfileRepo, Farmer


# ─── engine results that trigger escalation ──────────────────────────────────

def _rule(field, op, value, i=1, source="Official guideline text", unit=None):
    return EligibilityRuleRow(id=i, scheme_id=1, field_name=field, operator=op, value_json=value,
                              source_text=source, unit=unit, rule_order=i)


PROFILE = {"state": "Karnataka", "land_size_acres": 3.0, "age": 41, "gender": "female", "category": "SC",
           "name": "Lakshmi", "phone_number": "9876543210", "aadhaar_number": "1234 5678 9012",
           "email": "l@example.com"}
CANDIDATES = [{"scheme_id": "CONFLICTED", "official_url": "https://example.gov.in/conflicted"},
              {"scheme_id": "NO_RULES", "official_url": "https://example.gov.in/norules"}]


def conflicted():
    """land ≤ 5 AND land ≥ 10: the scheme's own rules contradict each other → RULE_CONFLICT."""
    return evaluate_scheme("CONFLICTED", "Conflicted Scheme",
                           [_rule("land_size_acres", "LTE", 5, 1, "Up to 5 acres"),
                            _rule("land_size_acres", "GTE", 10, 2, "At least 10 acres")],
                           PROFILE, source_url="https://example.gov.in/conflicted")


def unverifiable():
    return evaluate_scheme("NO_RULES", "Scheme Without Rules", [], PROFILE)


async def escalate(session="s1", results=None, source_conflicts=None, errors=None):
    return await wf.escalate(session, "ragi farmer schemes", PROFILE,
                             results if results is not None else [conflicted()],
                             CANDIDATES, source_conflicts or [], errors or {})


def make_case(**kw) -> str:
    return asyncio.run(escalate(**kw))["case_id"]


# ─── environment ─────────────────────────────────────────────────────────────

class FakeAudit:
    def __init__(self):
        self.events = []

    async def record(self, actor, action, target_type=None, target_id=None, details=None, outcome="SUCCESS",
                     correlation_id=None):
        self.events.append(SimpleNamespace(actor=actor.label, action=action, target_id=target_id,
                                           details=details or {}, outcome=outcome))


@pytest.fixture
def env(monkeypatch):
    auth = FakeAuthRepo()
    prof = FakeProfileRepo(auth)
    audit = FakeAudit()
    from app.core.config import settings
    from app.database.repositories import audit_repository
    monkeypatch.setattr("app.services.auth_service.repo", auth)
    monkeypatch.setattr("app.services.profile_service.profile_repo", prof)
    monkeypatch.setattr("app.api.auth.is_db_available", lambda: True)
    monkeypatch.setattr("app.api.deps.is_db_available", lambda: True)
    monkeypatch.setattr(audit_repository, "record", audit.record)
    monkeypatch.setattr(review_service, "_review_cases", {})
    monkeypatch.setattr(review_service, "_audit_log", [])
    monkeypatch.setattr(review_service, "_review_grants", {})
    monkeypatch.setattr(settings, "REVIEW_API_KEY", None)
    for name in ("send_verification_email", "send_password_reset_email",
                 "send_account_exists_email", "send_password_changed_email"):
        async def _noop(*a, **k):
            return True
        monkeypatch.setattr(f"app.services.auth_service.email_service.{name}", _noop)
    limiter.reset()

    def user(email, role="FARMER"):
        f = Farmer(auth, email)
        pk = next(a.id for a in auth.farmers.values() if a.email == email)
        auth._update(pk, role=role)
        if role == "REVIEWER":                         # approved by an administrator
            auth._update(pk, reviewer_approved_at=datetime.now(timezone.utc), reviewer_approved_by="admin")
        f.email, f.pk = email, pk
        f.post = lambda path, body=None, csrf=True: f.c.post(
            path, json=body or {}, headers={"X-CSRF-Token": f.csrf} if csrf else {})
        f.get = lambda path, **params: f.c.get(path, params=params)
        return f

    yield SimpleNamespace(auth=auth, prof=prof, audit=audit, user=user)
    limiter.reset()


def version(u, cid):
    """From the queue summary (the full case is visible only once it is yours)."""
    return next(c["version"] for c in u.get("/review-cases").json()["cases"] if c["case_id"] == cid)


# ─── queue ───────────────────────────────────────────────────────────────────

class TestQueue:
    def test_status_reason_and_assignment_filters_with_counts(self, env):
        r1, r2 = env.user("r1@example.com", "REVIEWER"), env.user("r2@example.com", "REVIEWER")
        a = make_case(session="s1")                                          # RULE_CONFLICT
        b = make_case(session="s2", results=[unverifiable()])                # UNVERIFIABLE
        c = make_case(session="s3", results=[], errors={"db": "down", "web": "timeout"})  # SYSTEM_ERROR
        assert r1.post(f"/review-cases/{b}/claim").status_code == 200
        assert r2.post(f"/review-cases/{c}/claim").status_code == 200

        body = r1.get("/review-cases", status="PENDING").json()
        assert [x["case_id"] for x in body["cases"]] == [a] and body["total"] == 1
        assert body["cases"][0]["access"] == "queue"
        # stats cover the caller's scope only: r2's case is invisible to r1
        assert body["stats"] == {"total": 2, "pending": 1, "in_review": 1, "resolved": 0, "dismissed": 0,
                                 "awaiting_verification": 0}
        assert [x["case_id"] for x in r1.get("/review-cases", status="IN_REVIEW").json()["cases"]] == [b]
        assert [x["case_id"] for x in r1.get("/review-cases", assigned="me").json()["cases"]] == [b]
        assert [x["case_id"] for x in r1.get("/review-cases", assigned="unassigned").json()["cases"]] == [a]
        assert r1.get("/review-cases", reason="SYSTEM_ERROR").json()["cases"] == []
        assert [x["case_id"] for x in r2.get("/review-cases", reason="SYSTEM_ERROR").json()["cases"]] == [c]
        page = r1.get("/review-cases", limit=1, offset=1).json()
        assert page["total"] == 2 and len(page["cases"]) == 1
        assert r1.get("/review-cases", status="LATER").status_code == 400
        assert r1.get("/review-cases", assigned="them").status_code == 422
        assert r1.get("/review-cases", limit=0).status_code == 422

    def test_open_cases_oldest_first_closed_newest_first(self, env):
        r = env.user("r@example.com", "REVIEWER")
        ids = [make_case(session=f"s{i}") for i in range(3)]
        assert [x["case_id"] for x in r.get("/review-cases", status="PENDING").json()["cases"]] == ids
        for cid in ids:
            r.post(f"/review-cases/{cid}/dismiss", {"note": "duplicate report"})
        assert [x["case_id"] for x in r.get("/review-cases", status="DISMISSED").json()["cases"]] == ids[::-1]


# ─── what a reviewer sees ────────────────────────────────────────────────────

class TestCaseContent:
    def test_scheme_reason_evidence_urls_conflicts_and_minimal_profile(self, env):
        r = env.user("r@example.com", "REVIEWER")
        cid = make_case()
        assert r.get(f"/review-cases/{cid}").status_code == 404           # queue case: not yet yours
        r.post(f"/review-cases/{cid}/claim")
        c = r.get(f"/review-cases/{cid}").json()["case"]
        assert c["reason"] == "RULE_CONFLICT" and c["status"] == "IN_REVIEW"
        assert c["schemes"] == [{"scheme_id": "CONFLICTED", "name": "Conflicted Scheme",
                                 "official_url": "https://example.gov.in/conflicted"}]
        assert {e["text"] for e in c["evidence"]} == {"Up to 5 acres", "At least 10 acres"}
        assert all(e["url"] == "https://example.gov.in/conflicted" for e in c["evidence"])
        assert c["rule_conflicts"][0]["type"] == "CONTRADICTORY_BOUNDS"
        assert c["rule_conflicts"][0]["scheme_id"] == "CONFLICTED"
        # only what the triggering rules use (+ state): no age / gender / category, no identity
        assert c["profile_snapshot"] == {"state": "Karnataka", "land_size_acres": 3.0}
        text = str(c)
        for secret in ("Lakshmi", "9876543210", "1234 5678 9012", "l@example.com"):
            assert secret not in text
        assert "farmer_pk" not in c and "session_id" not in c and c["farmer_follows_case"] is False
        assert c["eligibility_results"][0]["status"] == "UNVERIFIABLE"

    def test_source_conflict_values_and_failed_channels(self, env):
        r = env.user("r@example.com", "REVIEWER")
        sc = [{"scheme_id": "NO_RULES", "field": "benefit_amount",
               "values": {"database": "₹6000", "web": "₹8000"}, "sources": ["database", "web"]}]
        cid = make_case(results=[evaluate_scheme("NO_RULES", "Scheme Without Rules",
                                                 [_rule("state", "IN", ["Karnataka"])], PROFILE)],
                        source_conflicts=sc)
        r.post(f"/review-cases/{cid}/claim")
        c = r.get(f"/review-cases/{cid}").json()["case"]
        assert c["reason"] == "SOURCE_CONFLICT" and c["source_conflicts"] == sc
        assert c["schemes"][0]["official_url"] == "https://example.gov.in/norules"
        cid2 = make_case(session="s9", results=[], errors={"db": "down", "graph": "error", "web": None})
        r.post(f"/review-cases/{cid2}/claim")
        c2 = r.get(f"/review-cases/{cid2}").json()["case"]
        assert c2["reason"] == "SYSTEM_ERROR" and c2["failed_channels"] == ["db", "graph"]


# ─── workflow transitions ────────────────────────────────────────────────────

class TestTransitions:
    def test_claim_release_and_assignee_only(self, env):
        r1, r2 = env.user("r1@example.com", "REVIEWER"), env.user("r2@example.com", "REVIEWER")
        cid = make_case()
        c = r1.post(f"/review-cases/{cid}/claim").json()["case"]
        assert (c["status"], c["assignee"], c["version"]) == ("IN_REVIEW", "r1@example.com", 2)
        assert c["assigned_at"]
        for path, body in ((f"/review-cases/{cid}/claim", {}), (f"/review-cases/{cid}/release", {}),
                           (f"/review-cases/{cid}/resolve", {"action": "APPROVE", "note": "looks right"}),
                           (f"/review-cases/{cid}/dismiss", {"note": "not needed"})):
            resp = r2.post(path, body)
            assert resp.status_code == 404 and resp.json()["detail"]["code"] == "NOT_FOUND", path
        back = r1.post(f"/review-cases/{cid}/release").json()["case"]
        assert (back["status"], back["assignee"]) == ("PENDING", None)
        assert r2.post(f"/review-cases/{cid}/claim").json()["case"]["assignee"] == "r2@example.com"

    @pytest.mark.parametrize("action,decision", [("APPROVE", "APPROVE"), ("REJECT", "REJECT"),
                                                 ("MARK_UNVERIFIABLE", "MARK_UNVERIFIABLE"), ("resolve", "RESOLVE")])
    def test_each_decision_resolves_and_is_final(self, env, action, decision):
        r = env.user("r@example.com", "REVIEWER")
        cid = make_case()
        early = r.post(f"/review-cases/{cid}/resolve", {"action": action, "note": "checked portal"})
        assert early.status_code == 409 and early.json()["detail"]["code"] == "INVALID_TRANSITION"
        r.post(f"/review-cases/{cid}/claim")
        no_note = r.post(f"/review-cases/{cid}/resolve", {"action": action, "note": "  "})
        assert no_note.status_code == 422 and no_note.json()["detail"]["code"] == "NOTE_REQUIRED"
        c = r.post(f"/review-cases/{cid}/resolve", {"action": action, "note": "checked the portal"}).json()["case"]
        assert (c["status"], c["decision"], c["reviewer_id"]) == ("RESOLVED", decision, "r@example.com")
        assert c["reviewer_note"] == "checked the portal" and c["reviewed_at"]
        for path, body in ((f"/review-cases/{cid}/resolve", {"action": "APPROVE", "note": "again!"}),
                           (f"/review-cases/{cid}/resolve", {"action": "REQUEST_INFORMATION", "note": "more"}),
                           (f"/review-cases/{cid}/dismiss", {"note": "not needed"}), (f"/review-cases/{cid}/claim", {}),
                           (f"/review-cases/{cid}/release", {})):
            assert r.post(path, body).status_code == 409, path

    def test_request_additional_verification_keeps_the_case_open(self, env):
        r = env.user("r@example.com", "REVIEWER")
        cid = make_case()
        c = r.post(f"/review-cases/{cid}/resolve", {"action": "REQUEST_INFORMATION",
                                                    "note": "Ask the district office"}).json()["case"]
        assert (c["status"], c["assignee"], c["awaiting_verification"]) == ("IN_REVIEW", "r@example.com", True)
        assert r.get("/review-cases").json()["stats"]["awaiting_verification"] == 1
        c = r.post(f"/review-cases/{cid}/resolve", {"action": "APPROVE", "note": "office confirmed"}).json()["case"]
        assert (c["status"], c["awaiting_verification"]) == ("RESOLVED", False)

    def test_dismiss_needs_a_note(self, env):
        r = env.user("r@example.com", "REVIEWER")
        cid = make_case()
        assert r.post(f"/review-cases/{cid}/dismiss", {}).status_code == 422
        c = r.post(f"/review-cases/{cid}/dismiss", {"note": "duplicate of an open case"}).json()["case"]
        assert c["status"] == "DISMISSED" and c["decision"] is None

    def test_unknown_action_and_case(self, env):
        r = env.user("r@example.com", "REVIEWER")
        cid = make_case()
        assert r.post(f"/review-cases/{cid}/resolve", {"action": "MAYBE", "note": "x y z"}).status_code == 400
        assert r.post("/review-cases/nope/claim").status_code == 404
        assert r.get("/review-cases/nope").status_code == 404
        assert r.get("/review-cases/bad id!").status_code in (404, 422)

    def test_admin_reads_and_assigns_but_never_decides(self, env):
        admin = env.user("admin@example.com", "ADMIN")
        r1, r2 = env.user("r1@example.com", "REVIEWER"), env.user("r2@example.com", "REVIEWER")
        farmer = env.user("f@example.com")
        cid = make_case()
        assert admin.get(f"/review-cases/{cid}").status_code == 200
        assert admin.post(f"/review-cases/{cid}/claim").status_code == 403
        assert admin.post(f"/review-cases/{cid}/resolve", {"action": "APPROVE", "note": "fine"}).status_code == 403
        assert admin.post(f"/review-cases/{cid}/comments", {"text": "please check"}).status_code == 403
        bad = admin.post(f"/review-cases/{cid}/assign", {"reviewer_email": farmer.email})
        assert bad.status_code == 422 and bad.json()["detail"]["code"] == "NOT_A_REVIEWER"
        c = admin.post(f"/review-cases/{cid}/assign", {"reviewer_email": "R1@example.com"}).json()["case"]
        assert (c["status"], c["assignee"]) == ("IN_REVIEW", "r1@example.com")
        assert r2.post(f"/review-cases/{cid}/resolve", {"action": "APPROVE", "note": "checked it"}).status_code == 404
        c = admin.post(f"/review-cases/{cid}/assign", {"reviewer_email": r2.email}).json()["case"]  # reassign
        assert c["assignee"] == r2.email
        assert r2.post(f"/review-cases/{cid}/resolve", {"action": "APPROVE", "note": "verified"}).status_code == 200
        assert r1.post(f"/review-cases/{cid}/assign", {"reviewer_email": r1.email}).status_code == 403
        env.auth._update(r1.pk, is_active=False)
        assert admin.post(f"/review-cases/{make_case(session='z')}/assign",
                          {"reviewer_email": r1.email}).status_code == 422          # inactive reviewer

    def test_farmers_and_anonymous_are_refused(self, env):
        from fastapi.testclient import TestClient
        from app.main import app
        f = env.user("f@example.com")
        cid = make_case()
        assert f.get("/review-cases").status_code == 403
        assert f.post(f"/review-cases/{cid}/claim").status_code == 403
        assert TestClient(app).get(f"/review-cases/{cid}").status_code == 401

    def test_reviewer_identity_and_rules_cannot_be_sent(self, env):
        r = env.user("r@example.com", "REVIEWER")
        cid = make_case()
        r.post(f"/review-cases/{cid}/claim")
        for extra in ({"reviewer_id": "someone"}, {"eligibility_rules": []}, {"status": "RESOLVED"}):
            assert r.post(f"/review-cases/{cid}/resolve",
                          {"action": "APPROVE", "note": "fine", **extra}).status_code == 422


# ─── concurrency ─────────────────────────────────────────────────────────────

class TestConcurrency:
    def test_stale_version_is_refused_and_changes_nothing(self, env):
        r = env.user("r@example.com", "REVIEWER")
        cid = make_case()
        v = version(r, cid)
        r.post(f"/review-cases/{cid}/claim", {"expected_version": v})
        resp = r.post(f"/review-cases/{cid}/resolve", {"action": "APPROVE", "note": "fine", "expected_version": v})
        assert resp.status_code == 409 and resp.json()["detail"]["code"] == "VERSION_CONFLICT"
        assert r.get(f"/review-cases/{cid}").json()["case"]["status"] == "IN_REVIEW"

    @pytest.mark.asyncio
    async def test_simultaneous_claims_only_one_wins(self, env):
        case = await escalate()
        ps = [Principal(role=None, label=f"rev{i}@example.com", account_pk=100 + i,
                        permissions=permissions_for("REVIEWER")) for i in range(5)]
        results = await asyncio.gather(*(wf.claim(p, case["case_id"], case["version"]) for p in ps),
                                       return_exceptions=True)
        winners = [x for x in results if isinstance(x, dict)]
        losers = [x for x in results if isinstance(x, wf.ReviewError)]
        assert len(winners) == 1 and len(losers) == 4 and all(e.status in (404, 409) for e in losers)
        stored = review_service.get_case(case["case_id"])
        assert stored.assignee == winners[0]["assignee"] and stored.version == 2
        assert sum(1 for e in review_service.get_audit_log(case["case_id"]) if e.action == "ASSIGNED") == 1

    @pytest.mark.asyncio
    async def test_double_submitted_decision_is_recorded_once(self, env):
        case = await escalate()
        p = Principal(role=None, label="rev@example.com", account_pk=7, permissions=permissions_for("REVIEWER"))
        claimed = await wf.claim(p, case["case_id"])
        results = await asyncio.gather(
            wf.act(p, case["case_id"], wf.ReviewAction.APPROVE, "checked", claimed["version"]),
            wf.act(p, case["case_id"], wf.ReviewAction.REJECT, "checked", claimed["version"]),
            return_exceptions=True)
        assert sum(isinstance(x, dict) for x in results) == 1
        decisions = [e.action for e in review_service.get_audit_log(case["case_id"])
                     if e.action in ("APPROVE", "REJECT")]
        assert len(decisions) == 1

    @pytest.mark.asyncio
    async def test_concurrent_escalations_open_one_case(self, env):
        cases = await asyncio.gather(*(escalate(session="same") for _ in range(5)))
        assert len({c["case_id"] for c in cases}) == 1
        assert len(review_service._review_cases) == 1


# ─── audit trail and comments ────────────────────────────────────────────────

class TestAudit:
    def test_history_and_audit_record_every_step(self, env):
        r = env.user("r@example.com", "REVIEWER")
        cid = make_case()
        r.post(f"/review-cases/{cid}/claim")
        assert r.post(f"/review-cases/{cid}/comments", {"text": "Checking the gazette, call 9876543210"}).status_code == 201
        r.post(f"/review-cases/{cid}/resolve", {"action": "REQUEST_INFORMATION", "note": "Asked the office"})
        r.post(f"/review-cases/{cid}/resolve", {"action": "REJECT", "note": "Bounds are a typo in the source",
                                                "data_correction_needed": True})
        body = r.get(f"/review-cases/{cid}").json()
        h = body["history"]
        assert [e["event"] for e in h] == ["CREATED", "ASSIGNED", "COMMENT", "VERIFICATION_REQUESTED", "REJECT"]
        assert [e["actor"] for e in h] == ["system"] + ["r@example.com"] * 4
        assert [(e["from_status"], e["to_status"]) for e in h] == [
            (None, "PENDING"), ("PENDING", "IN_REVIEW"), ("IN_REVIEW", "IN_REVIEW"),
            ("IN_REVIEW", "IN_REVIEW"), ("IN_REVIEW", "RESOLVED")]
        assert all(e["created_at"] for e in h)
        assert h[2]["note"] == "Checking the gazette, call [phone]"          # contact data redacted
        assert body["audit_log"][-1] == {"action": "REJECT", "reviewer": "r@example.com",
                                         "timestamp": h[-1]["created_at"], "note": "Bounds are a typo in the source"}
        audit = [(e.action, e.actor) for e in env.audit.events if e.target_id == cid]
        assert audit == [("REVIEW_CASE_CREATED", "system"), ("REVIEW_ASSIGNED", "r@example.com"),
                         ("REVIEW_COMMENTED", "r@example.com"), ("REVIEW_REQUEST_INFORMATION", "r@example.com"),
                         ("REVIEW_REJECT", "r@example.com"), ("REVIEW_CASE_VIEWED", "r@example.com")]
        decision = next(e for e in env.audit.events if e.action == "REVIEW_REJECT")
        assert decision.details["decision"] == "REJECT"

    def test_comments_need_text_and_reviewer_permission(self, env):
        r = env.user("r@example.com", "REVIEWER")
        cid = make_case()
        assert r.post(f"/review-cases/{cid}/comments", {"text": "not mine yet"}).status_code == 404
        r.post(f"/review-cases/{cid}/claim")
        assert r.post(f"/review-cases/{cid}/comments", {"text": " "}).status_code == 422
        assert r.post(f"/review-cases/{cid}/comments", {"text": "x" * 2001}).status_code == 422
        assert r.post(f"/review-cases/{cid}/comments", {"text": "fine"}, csrf=False).status_code == 403
        r.post(f"/review-cases/{cid}/dismiss", {"note": "duplicate"})
        assert r.post(f"/review-cases/{cid}/comments", {"text": "closing note"}).status_code == 201  # after close

    def test_there_is_no_way_to_edit_or_delete_history(self, env):
        from app.main import app
        paths = {getattr(rt, "path", "") for rt in app.routes}
        methods = {(m, rt.path) for rt in app.routes for m in getattr(rt, "methods", set())
                   if rt.path.startswith("/review-cases")}
        assert not any(m in ("PUT", "PATCH", "DELETE") for m, _ in methods)
        assert "/review-cases/{case_id}/history" not in paths


# ─── human decisions are separate from automated results ─────────────────────

class TestSeparation:
    def test_decision_never_changes_the_automated_result(self, env):
        r = env.user("r@example.com", "REVIEWER")
        cid = make_case()
        r.post(f"/review-cases/{cid}/claim")
        before = r.get(f"/review-cases/{cid}").json()["case"]["eligibility_results"]
        c = r.post(f"/review-cases/{cid}/resolve", {"action": "REJECT", "note": "rule is wrong",
                                                    "data_correction_needed": True}).json()["case"]
        assert c["eligibility_results"] == before and c["data_correction_needed"] is True
        assert c["decision"] == "REJECT"

    def test_data_correction_flag_only_on_reject(self, env):
        r = env.user("r@example.com", "REVIEWER")
        cid = make_case()
        r.post(f"/review-cases/{cid}/claim")
        c = r.post(f"/review-cases/{cid}/resolve", {"action": "APPROVE", "note": "checked it",
                                                    "data_correction_needed": True}).json()["case"]
        assert c["data_correction_needed"] is False

    def test_review_code_never_writes_scheme_data(self):
        import inspect
        from app.api import review as api
        for module in (wf, api):
            src = inspect.getsource(module)
            for forbidden in ("eligibility_rules SET", "UPDATE schemes", "INSERT INTO eligibility_rules",
                              "SchemeRepository", "RuleRepository", "import_corpus"):
                assert forbidden not in src, (module.__name__, forbidden)


# ─── escalation and what the farmer sees ─────────────────────────────────────

class TestEscalationAndFarmer:
    @pytest.mark.asyncio
    async def test_one_open_case_per_session_and_reason_then_a_new_one(self, env):
        first = await escalate(session="s1")
        assert (await escalate(session="s1"))["case_id"] == first["case_id"]
        assert (await escalate(session="s1", results=[unverifiable()]))["case_id"] != first["case_id"]
        p = Principal(role=None, label="rev@example.com", account_pk=9, permissions=permissions_for("REVIEWER"))
        await wf.claim(p, first["case_id"])
        await wf.act(p, first["case_id"], wf.ReviewAction.APPROVE, "checked it")
        assert (await escalate(session="s1"))["case_id"] != first["case_id"]
        assert await escalate(session="s2", results=[conflicted().model_copy(update={"conflicts": []})]) is not None

    @pytest.mark.asyncio
    async def test_pipeline_node_escalates_and_keeps_results(self, env):
        from app.agents.recommendation_agent import recommendation_agent
        res = unverifiable()
        out = await recommendation_agent({"eligibility_results": [res], "session_id": "pipe-1",
                                          "original_query": "q", "profile": PROFILE,
                                          "merged_candidates": CANDIDATES})
        assert out["needs_review"] and out["review_reason"] == "UNVERIFIABLE"
        assert review_service.get_case(out["review_case_id"]).schemes[0]["official_url"] == \
            "https://example.gov.in/norules"
        assert out["recommendation_results"][0].eligibility_status.value == "UNVERIFIABLE"

    @pytest.mark.asyncio
    async def test_pipeline_node_with_no_results_and_failed_channels(self, env):
        """Regression: the no-results path must await the escalation (it returned a coroutine)."""
        from app.agents.recommendation_agent import recommendation_agent
        out = await recommendation_agent({"eligibility_results": [], "session_id": "pipe-2", "original_query": "q",
                                          "profile": {}, "retrieval_errors": {"db": "down", "web": "timeout"}})
        assert out["recommendation_results"] == [] and out["needs_review"] is True
        assert out["review_reason"] == "SYSTEM_ERROR"
        assert review_service.get_case(out["review_case_id"]).failed_channels == ["db", "web"]

    def test_signed_in_farmer_follows_their_case_and_sees_the_outcome(self, env, monkeypatch):
        f, other = env.user("f@example.com"), env.user("o@example.com")
        r = env.user("r@example.com", "REVIEWER")
        cid = make_case(session="chat-1")

        class FakeGraph:
            async def aget_state(self, config):
                return SimpleNamespace(values={})

            async def ainvoke(self, inputs, config):
                return {"response_status": "schemes_found", "response_text": "Found", "messages": [],
                        "response_schemes": [], "needs_review": True, "review_reason": "RULE_CONFLICT",
                        "review_case_id": cid}

        monkeypatch.setattr("app.api.chat.kisan_agent", FakeGraph())
        resp = f.post("/chat", {"message": "schemes for me", "language": "en"})
        assert resp.status_code == 200 and resp.json()["review"]["case_id"] == cid
        r.post(f"/review-cases/{cid}/claim")
        assert r.get(f"/review-cases/{cid}").json()["case"]["farmer_follows_case"] is True

        mine = f.get("/farmers/me/review-cases").json()
        assert mine["open"] == 1
        item = mine["items"][0]
        assert item["schemes"] == [{"scheme_id": "CONFLICTED", "name": "Conflicted Scheme"}]
        assert item["open"] and "unconfirmed" in item["outcome_text"]
        assert "contradict" in item["reason_text"]
        assert other.get("/farmers/me/review-cases").json() == {"items": [], "open": 0}

        r.post(f"/review-cases/{cid}/claim")
        r.post(f"/review-cases/{cid}/resolve", {"action": "MARK_UNVERIFIABLE", "note": "Secret internal note"})
        item = f.get("/farmers/me/review-cases").json()["items"][0]
        assert not item["open"] and "couldn't verify" in item["outcome_text"]
        text = str(item)
        assert "r@example.com" not in text and "Secret internal note" not in text and "evidence" not in text

    def test_anonymous_chat_is_not_linked_and_dashboard_flags_open_cases(self, env, monkeypatch):
        cid = make_case(session="anon")
        assert review_service.get_case(cid).farmer_pk is None
        f = env.user("f@example.com")
        asyncio.run(wf.link_farmer(cid, f.pk))
        assert asyncio.run(wf.open_scheme_ids_for_farmer(f.pk)) == {"CONFLICTED"}
        from app.services.dashboard_service import _schemes_under_review
        assert asyncio.run(_schemes_under_review(f.farmer_id)) == {"CONFLICTED"}
        p = Principal(role=None, label="rev@example.com", account_pk=9, permissions=permissions_for("REVIEWER"))
        asyncio.run(wf.dismiss(p, cid, "false alarm"))
        assert asyncio.run(wf.open_scheme_ids_for_farmer(f.pk)) == set()

    def test_farmer_route_needs_sign_in(self, env):
        from fastapi.testclient import TestClient
        from app.main import app
        assert TestClient(app).get("/farmers/me/review-cases").status_code == 401
