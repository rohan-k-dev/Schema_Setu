"""
Reviewer authorization policy (docs/HUMAN_REVIEW.md, "Access policy") — security tests through
the real HTTP API with real cookie sessions: unapproved and unauthorised callers, cross-case
access, direct API calls without the UI, reviewer-to-admin escalation, cases outside the
reviewer's scope (view / modify), explicit expiring grants, field-level minimisation, access
auditing, scraping limits, staff session expiry, revocation and reauthentication.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.rate_limit import limiter
from app.main import app
from app.services import review_service
from app.services import review_workflow as wf
from app.tests.fake_auth_repo import FakeAuthRepo
from app.tests.fake_ops import FakeAudit
from app.tests.test_profile_module import ORIGIN, UA, FakeProfileRepo
from app.tests.test_rbac import FakeAdminRepo
from app.tests.test_review_workflow import escalate, unverifiable

PASSWORD = "KisanPass123"


# ─── environment ─────────────────────────────────────────────────────────────

class Account:
    """A signed-in account with its own browser (cookie jar) and CSRF token."""

    def __init__(self, env, email, role="FARMER", approved=True):
        self.env, self.email = env, email
        self.c = TestClient(app, headers={"User-Agent": UA, "Origin": ORIGIN})
        assert self.c.post("/auth/register", json={"email": email, "password": PASSWORD}).status_code == 202
        self.pk = next(f.id for f in env.auth.farmers.values() if f.email == email)
        self.farmer_id = env.auth.farmers[self.pk].farmer_id
        env.auth._update(self.pk, is_verified=True, role=role)
        if role == "REVIEWER" and approved:
            env.auth._update(self.pk, reviewer_approved_at=datetime.now(timezone.utc), reviewer_approved_by="admin")
        self.login()

    def login(self):
        r = self.c.post("/auth/login", json={"email": self.email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        self.csrf = r.json()["csrf_token"]

    def call(self, method, path, body=None, csrf=True):
        headers = {"X-CSRF-Token": self.csrf} if csrf and method != "GET" else {}
        if method == "GET":
            return self.c.get(path, params=body)
        return self.c.request(method, path, json=body if body is not None else {}, headers=headers)

    def session(self):
        return max((s for s in self.env.auth.sessions.values() if s.farmer_id == self.pk and not s.revoked_at),
                   key=lambda s: s.id)

    def age_session(self, created_minutes=0, idle_minutes=0, reauth_minutes=None):
        s = self.session()
        now = datetime.now(timezone.utc)
        self.env.auth.sessions[s.id] = s.model_copy(update={
            "created_at": now - timedelta(minutes=created_minutes),
            "last_seen_at": now - timedelta(minutes=idle_minutes),
            "reauthenticated_at": None if reauth_minutes is None else now - timedelta(minutes=reauth_minutes)})


@pytest.fixture
def env(monkeypatch):
    auth = FakeAuthRepo()
    audit = FakeAudit()
    admin_repo = FakeAdminRepo(auth, audit)
    from app.database.repositories import audit_repository
    monkeypatch.setattr("app.services.auth_service.repo", auth)
    monkeypatch.setattr("app.services.profile_service.profile_repo", FakeProfileRepo(auth))
    monkeypatch.setattr("app.services.admin_service.repo", admin_repo)
    monkeypatch.setattr("app.api.auth.is_db_available", lambda: True)
    monkeypatch.setattr("app.api.deps.is_db_available", lambda: True)
    monkeypatch.setattr(audit_repository, "record", audit.record)
    monkeypatch.setattr("app.api.deps.audit_repo", audit)
    monkeypatch.setattr(review_service, "_review_cases", {})
    monkeypatch.setattr(review_service, "_audit_log", [])
    monkeypatch.setattr(review_service, "_review_grants", {})
    monkeypatch.setattr(settings, "REVIEW_API_KEY", "dev-review-key-123")
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    for name in ("send_password_reset_email",
                 "send_account_exists_email", "send_password_changed_email"):
        async def _noop(*a, **k):
            return True
        monkeypatch.setattr(f"app.services.auth_service.email_service.{name}", _noop)
    limiter.reset()
    ns = SimpleNamespace(auth=auth, audit=audit)
    ns.account = lambda email, role="FARMER", approved=True: Account(ns, email, role, approved)
    yield ns
    limiter.reset()


def new_case(session="s1", results=None):
    return asyncio.run(escalate(session=session, results=results))["case_id"]


def claimed_by(acc, session="s1"):
    cid = new_case(session)
    assert acc.call("POST", f"/review-cases/{cid}/claim").status_code == 200
    return cid


def audit_rows(env, action=None, actor=None, outcome=None):
    return [r for r in env.audit.rows if (action is None or r.action == action)
            and (actor is None or r.actor_label == actor) and (outcome is None or r.outcome == outcome)]


def every_case_endpoint(cid):
    return [("GET", f"/review-cases/{cid}", None), ("POST", f"/review-cases/{cid}/claim", {}),
            ("POST", f"/review-cases/{cid}/release", {}), ("POST", f"/review-cases/{cid}/comments", {"text": "look"}),
            ("POST", f"/review-cases/{cid}/resolve", {"action": "REQUEST_INFORMATION", "note": "verify"}),
            ("POST", f"/review-cases/{cid}/resolve", {"action": "APPROVE", "note": "fine by me"}),
            ("POST", f"/review-cases/{cid}/dismiss", {"note": "not needed"})]


# ─── approval: the REVIEWER role alone is not enough ─────────────────────────

class TestApproval:
    def test_unapproved_reviewer_gets_nothing_but_own_data(self, env):
        r = env.account("new-rev@example.com", "REVIEWER", approved=False)
        cid = new_case()
        assert r.call("GET", "/review-cases").status_code == 403
        assert r.call("GET", "/review-cases/stats/summary").status_code == 403
        for method, path, body in every_case_endpoint(cid):
            assert r.call(method, path, body).status_code == 403, path
        assert r.call("GET", "/farmers/me/profile").status_code in (200, 404)          # own data still works
        assert len(audit_rows(env, "ACCESS_DENIED", r.email, "DENIED")) >= 8
        assert review_service.get_case(cid).status.value == "PENDING"

    def test_admin_approves_and_revocation_ends_sessions(self, env):
        admin = env.account("admin@example.com", "ADMIN")
        r = env.account("rev@example.com", "REVIEWER", approved=False)
        ok = admin.call("PATCH", f"/admin/users/{r.farmer_id}/reviewer-approval", {"approved": True})
        assert ok.status_code == 200 and ok.json()["reviewer_approved"] is True
        assert r.call("GET", "/review-cases").status_code == 200
        off = admin.call("PATCH", f"/admin/users/{r.farmer_id}/reviewer-approval", {"approved": False})
        assert off.status_code == 200 and off.json()["reviewer_approved"] is False
        assert r.call("GET", "/review-cases").status_code == 401                     # sessions ended
        r.login()
        assert r.call("GET", "/review-cases").status_code == 403                     # and no access
        assert [x.action for x in audit_rows(env, actor=admin.email)
                if x.action.startswith("REVIEWER_")] == ["REVIEWER_APPROVED", "REVIEWER_APPROVAL_REVOKED"]

    def test_approval_rules(self, env):
        admin = env.account("admin@example.com", "ADMIN")
        farmer = env.account("f@example.com")
        assert admin.call("PATCH", f"/admin/users/{farmer.farmer_id}/reviewer-approval",
                          {"approved": True}).status_code == 422                     # not a reviewer
        assert admin.call("PATCH", f"/admin/users/{admin.farmer_id}/reviewer-approval",
                          {"approved": True}).status_code == 403                     # never yourself
        r = env.account("rev@example.com", "REVIEWER")
        admin.call("PATCH", f"/admin/users/{r.farmer_id}/role", {"role": "FARMER"})
        admin.call("PATCH", f"/admin/users/{r.farmer_id}/role", {"role": "REVIEWER"})
        assert env.auth.farmers[r.pk].reviewer_approved_at is None                   # role change clears it
        r.login()
        assert r.call("GET", "/review-cases").status_code == 403

    def test_principal_rebuilt_every_request(self, env):
        r = env.account("rev@example.com", "REVIEWER")
        assert r.call("GET", "/review-cases").status_code == 200
        env.auth._update(r.pk, reviewer_approved_at=None)                             # revoked directly in DB
        assert r.call("GET", "/review-cases").status_code == 403


# ─── cross-case access and scope ─────────────────────────────────────────────

class TestScope:
    def test_another_reviewers_case_does_not_exist_for_you(self, env):
        a, b = env.account("a@example.com", "REVIEWER"), env.account("b@example.com", "REVIEWER")
        cid = claimed_by(a)
        nonexistent = b.call("GET", "/review-cases/000000000000")
        for method, path, body in every_case_endpoint(cid):
            resp = b.call(method, path, body)
            assert resp.status_code == 404, (path, resp.status_code)
            assert resp.json() == nonexistent.json()                                  # no existence oracle
        denied = [d for d in audit_rows(env, "REVIEW_CASE_ACCESS_DENIED", b.email, "DENIED") if d.target_id == cid]
        assert len(denied) == 7 and {d.details["attempt"] for d in denied} >= {"view", "claim", "decide", "dismiss"}
        c = review_service.get_case(cid)
        assert (c.status.value, c.assignee, c.version) == ("IN_REVIEW", a.email, 2)  # nothing changed

    def test_listing_and_counts_cover_only_your_scope(self, env):
        a, b = env.account("a@example.com", "REVIEWER"), env.account("b@example.com", "REVIEWER")
        mine = claimed_by(a, "s1")
        other = claimed_by(b, "s2")
        queued = new_case("s3")
        body = a.call("GET", "/review-cases").json()
        ids = {c["case_id"]: c["access"] for c in body["cases"]}
        assert ids == {mine: "assigned", queued: "queue"} and other not in ids
        assert body["stats"]["total"] == 2
        assert a.call("GET", "/review-cases", {"status": "IN_REVIEW"}).json()["total"] == 1

    def test_queue_summaries_carry_no_farmer_or_evidence_data(self, env):
        a = env.account("a@example.com", "REVIEWER")
        cid = new_case()
        f = env.account("farmer@example.com")
        asyncio.run(wf.link_farmer(cid, f.pk))
        item = a.call("GET", "/review-cases").json()["cases"][0]
        assert set(item) == {"case_id", "reason", "status", "schemes", "assignee", "awaiting_verification",
                             "decision", "version", "created_at", "updated_at", "access"}
        assert a.call("GET", f"/review-cases/{cid}").status_code == 404               # details once yours
        a.call("POST", f"/review-cases/{cid}/claim")
        case = a.call("GET", f"/review-cases/{cid}").json()["case"]
        for hidden in ("farmer_pk", "session_id"):
            assert hidden not in case
        assert f.email not in str(case) and case["farmer_follows_case"] is True

    def test_question_text_is_minimised(self, env):
        a = env.account("a@example.com", "REVIEWER")
        case = asyncio.run(wf.escalate("s-q", "my aadhaar is 1234 5678 9012, call 9876543210",
                                       {"state": "Karnataka"}, [unverifiable()], [], [], {}))
        a.call("POST", f"/review-cases/{case['case_id']}/claim")
        q = a.call("GET", f"/review-cases/{case['case_id']}").json()["case"]["query"]
        assert "1234 5678 9012" not in q and "9876543210" not in q and "[number]" in q and "[phone]" in q

    def test_closed_cases_stay_with_their_reviewer(self, env):
        a, b = env.account("a@example.com", "REVIEWER"), env.account("b@example.com", "REVIEWER")
        cid = claimed_by(a)
        a.call("POST", f"/review-cases/{cid}/resolve", {"action": "APPROVE", "note": "checked portal"})
        assert a.call("GET", f"/review-cases/{cid}").status_code == 200
        assert b.call("GET", f"/review-cases/{cid}").status_code == 404
        assert b.call("GET", "/review-cases", {"status": "RESOLVED"}).json()["total"] == 0

    def test_self_assignment_can_be_switched_off(self, env, monkeypatch):
        a = env.account("a@example.com", "REVIEWER")
        cid = new_case()
        monkeypatch.setattr(settings, "REVIEW_SELF_ASSIGN", False)
        assert a.call("GET", "/review-cases").json()["cases"] == []
        assert a.call("POST", f"/review-cases/{cid}/claim").status_code == 404


# ─── explicit, expiring grants ───────────────────────────────────────────────

class TestGrants:
    def test_grantee_reads_and_comments_but_never_acts(self, env):
        admin = env.account("admin@example.com", "ADMIN")
        a, b = env.account("a@example.com", "REVIEWER"), env.account("b@example.com", "REVIEWER")
        cid = claimed_by(a)
        g = admin.call("POST", f"/review-cases/{cid}/grants", {"reviewer_email": b.email, "hours": 2})
        assert g.status_code == 201 and g.json()["grant"]["reviewer"] == b.email
        assert b.call("GET", f"/review-cases/{cid}").json()["access"] == "granted"
        assert b.call("POST", f"/review-cases/{cid}/comments", {"text": "second opinion: looks fine"}).status_code == 201
        for method, path, body in every_case_endpoint(cid)[1:3] + every_case_endpoint(cid)[4:]:
            assert b.call(method, path, body).status_code == 409, path               # assigned to a
        assert review_service.get_case(cid).assignee == a.email
        assert admin.call("GET", f"/review-cases/{cid}").json()["grants"][0]["reviewer"] == b.email

    def test_expired_and_revoked_grants_end_access(self, env):
        admin = env.account("admin@example.com", "ADMIN")
        a, b = env.account("a@example.com", "REVIEWER"), env.account("b@example.com", "REVIEWER")
        cid = claimed_by(a)
        admin.call("POST", f"/review-cases/{cid}/grants", {"reviewer_email": b.email, "hours": 1})
        review_service._review_grants[cid][b.pk]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        assert b.call("GET", f"/review-cases/{cid}").status_code == 404
        admin.call("POST", f"/review-cases/{cid}/grants", {"reviewer_email": b.email, "hours": 1})
        assert b.call("GET", f"/review-cases/{cid}").status_code == 200
        assert admin.call("POST", f"/review-cases/{cid}/grants/revoke", {"reviewer_email": b.email}).status_code == 204
        assert b.call("GET", f"/review-cases/{cid}").status_code == 404
        assert admin.call("POST", f"/review-cases/{cid}/grants/revoke",
                          {"reviewer_email": b.email}).status_code == 404
        assert [r.action for r in audit_rows(env, actor=admin.email) if r.target_id == cid
                and r.action.startswith("REVIEW_ACCESS")] == ["REVIEW_ACCESS_GRANTED", "REVIEW_ACCESS_GRANTED",
                                                               "REVIEW_ACCESS_REVOKED"]

    def test_grant_rules(self, env):
        admin = env.account("admin@example.com", "ADMIN")
        a = env.account("a@example.com", "REVIEWER")
        pending = env.account("p@example.com", "REVIEWER", approved=False)
        cid = claimed_by(a)
        for who, hours, code in ((pending.email, 2, 422), ("f@example.com", 2, 422), (a.email, 2, 409),
                                 ("b@example.com", 0, 422), ("b@example.com", 10_000, 422)):
            assert admin.call("POST", f"/review-cases/{cid}/grants",
                              {"reviewer_email": who, "hours": hours}).status_code == code, (who, hours)
        assert a.call("POST", f"/review-cases/{cid}/grants", {"reviewer_email": a.email}).status_code == 403


# ─── reviewer → administrator escalation ─────────────────────────────────────

class TestEscalation:
    def test_reviewer_cannot_use_any_administrator_operation(self, env):
        env.account("admin@example.com", "ADMIN")
        r = env.account("rev@example.com", "REVIEWER")
        other = env.account("other@example.com", "REVIEWER")
        cid = claimed_by(r)
        attempts = [
            ("POST", f"/review-cases/{cid}/assign", {"reviewer_email": other.email}),
            ("POST", f"/review-cases/{cid}/grants", {"reviewer_email": other.email}),
            ("POST", f"/review-cases/{cid}/grants/revoke", {"reviewer_email": other.email}),
            ("PATCH", f"/admin/users/{r.farmer_id}/role", {"role": "ADMIN"}),
            ("PATCH", f"/admin/users/{other.farmer_id}/reviewer-approval", {"approved": False}),
            ("PATCH", f"/admin/users/{other.farmer_id}/status", {"is_active": False}),
            ("GET", "/admin/users", None), ("GET", f"/admin/users/{other.farmer_id}", None),
            ("GET", "/admin/audit-events", None), ("GET", "/admin/ops/overview", None),
            ("POST", "/admin/ops/jobs", {"kind": "IMPORT_CORPUS", "dry_run": True, "reason": "x"}),
            ("GET", "/admin/scheme-changes", None), ("GET", "/admin/notifications/deliveries", None),
        ]
        for method, path, body in attempts:
            assert r.call(method, path, body).status_code == 403, path
        assert env.auth.farmers[r.pk].role == "REVIEWER" and env.auth.farmers[other.pk].reviewer_approved_at
        assert review_service.get_case(cid).assignee == r.email
        assert len(audit_rows(env, "ACCESS_DENIED", r.email, "DENIED")) == len(attempts)

    def test_review_key_is_review_only_and_never_sees_farmer_data(self, env):
        c = TestClient(app)
        key = {"X-Review-Key": "dev-review-key-123"}
        linked, anon = new_case("s1"), new_case("s2", results=[unverifiable()])
        f = env.account("farmer@example.com")
        asyncio.run(wf.link_farmer(linked, f.pk))
        listed = {x["case_id"] for x in c.get("/review-cases", headers=key).json()["cases"]}
        assert listed == {anon}
        assert c.get(f"/review-cases/{linked}", headers=key).status_code == 404
        assert c.get(f"/review-cases/{anon}", headers=key).status_code == 200
        for path, body in ((f"/review-cases/{anon}/assign", {"reviewer_email": "x@example.com"}),
                           (f"/review-cases/{anon}/grants", {"reviewer_email": "x@example.com"})):
            assert c.post(path, json=body, headers=key).status_code in (401, 403)
        assert c.get("/admin/users", headers=key).status_code == 401

    def test_reviewers_cannot_browse_farmer_profiles(self, env):
        r = env.account("rev@example.com", "REVIEWER")
        f = env.account("farmer@example.com")
        f.call("PUT", "/farmers/me/profile", {"state": "KA", "age": 44, "consent_given": True})
        own = r.call("GET", "/farmers/me/profile")
        assert own.status_code == 404                                               # their own (none), not f's
        assert r.call("GET", f"/admin/users/{f.farmer_id}").status_code == 403
        assert r.call("GET", "/farmers/me/profile", {"farmer_id": f.farmer_id}).status_code == 404
        paths = {getattr(rt, "path", "") for rt in app.routes}
        assert not any("{farmer_id}" in p and p.startswith("/farmers") for p in paths)


# ─── direct API calls without the UI ─────────────────────────────────────────

class TestDirectCalls:
    def test_every_review_endpoint_needs_a_valid_session(self, env):
        cid = new_case()
        anon = TestClient(app)
        forged = TestClient(app, cookies={settings.SESSION_COOKIE_NAME: "forged-session-token"})
        for method, path, body in every_case_endpoint(cid) + [("GET", "/review-cases", None),
                                                              ("POST", f"/review-cases/{cid}/assign", {"reviewer_email": "x@y.z"})]:
            for client in (anon, forged):
                resp = client.request(method, path, json=body) if method != "GET" else client.get(path)
                assert resp.status_code == 401, (path, resp.status_code)

    def test_csrf_and_stolen_cookie(self, env):
        r = env.account("rev@example.com", "REVIEWER")
        cid = new_case()
        assert r.call("POST", f"/review-cases/{cid}/claim", csrf=False).status_code == 403
        thief = TestClient(app, headers={"User-Agent": "Different Browser"},
                           cookies={settings.SESSION_COOKIE_NAME: r.c.cookies.get(settings.SESSION_COOKIE_NAME)})
        assert thief.get("/review-cases").status_code == 401                        # UA-bound session
        assert r.call("GET", "/review-cases").status_code == 401                    # and it was revoked

    def test_responses_are_not_cacheable(self, env):
        r = env.account("rev@example.com", "REVIEWER")
        cid = claimed_by(r)
        for path in ("/review-cases", f"/review-cases/{cid}", "/review-cases/stats/summary"):
            resp = r.call("GET", path)
            assert resp.headers["Cache-Control"].startswith("no-store") and resp.headers["Pragma"] == "no-cache"

    def test_bulk_viewing_is_rate_limited_and_audited(self, env, monkeypatch):
        monkeypatch.setattr(settings, "REVIEW_VIEWS_PER_10_MIN", 10)
        r = env.account("rev@example.com", "REVIEWER")
        cid = claimed_by(r)
        codes = [r.call("GET", f"/review-cases/{cid}").status_code for _ in range(12)]
        assert codes[:10] == [200] * 10 and codes[10:] == [429, 429]
        assert len(audit_rows(env, "REVIEW_CASE_VIEWED", r.email, "SUCCESS")) == 10
        assert len(audit_rows(env, "REVIEW_CASE_VIEWED", r.email, "DENIED")) == 2
        assert r.call("GET", "/review-cases", {"limit": 51}).status_code == 422       # no bulk page sizes


# ─── sessions and reauthentication ───────────────────────────────────────────

class TestSessions:
    def test_staff_idle_timeout_is_shorter_than_farmers(self, env):
        r, f = env.account("rev@example.com", "REVIEWER"), env.account("f@example.com")
        r.age_session(created_minutes=40, idle_minutes=settings.STAFF_SESSION_IDLE_MINUTES + 1)
        f.age_session(created_minutes=40, idle_minutes=settings.STAFF_SESSION_IDLE_MINUTES + 1)
        assert r.call("GET", "/review-cases").status_code == 401
        assert f.call("GET", "/farmers/me/review-cases").status_code == 200
        assert next(s for s in env.auth.sessions.values() if s.farmer_id == r.pk).revoked_reason == "idle_timeout"

    def test_staff_absolute_lifetime(self, env):
        r = env.account("rev@example.com", "REVIEWER")
        r.age_session(created_minutes=settings.STAFF_SESSION_ABSOLUTE_HOURS * 60 + 1, idle_minutes=1)
        assert r.call("GET", "/review-cases").status_code == 401
        assert next(s for s in env.auth.sessions.values()
                    if s.farmer_id == r.pk).revoked_reason == "staff_session_expired"

    def test_final_decisions_need_a_recent_sign_in(self, env):
        r = env.account("rev@example.com", "REVIEWER")
        cid = claimed_by(r)
        r.age_session(created_minutes=settings.REAUTH_WINDOW_MINUTES + 5, idle_minutes=1)
        for path, body in ((f"/review-cases/{cid}/resolve", {"action": "APPROVE", "note": "verified it"}),
                           (f"/review-cases/{cid}/dismiss", {"note": "duplicate case"})):
            resp = r.call("POST", path, body)
            assert resp.status_code == 403 and resp.json()["detail"]["code"] == "REAUTH_REQUIRED"
        assert review_service.get_case(cid).status.value == "IN_REVIEW"
        # low-risk steps still work without it
        assert r.call("POST", f"/review-cases/{cid}/comments", {"text": "checking"}).status_code == 201
        assert r.call("POST", f"/review-cases/{cid}/resolve",
                      {"action": "REQUEST_INFORMATION", "note": "asked"}).status_code == 200
        bad = r.call("POST", "/auth/reauthenticate", {"password": "wrong-password"})
        assert bad.status_code == 400 and bad.json()["error"]["code"] == "INVALID_PASSWORD"
        assert r.call("POST", "/auth/reauthenticate", {"password": PASSWORD}).status_code == 200
        assert r.call("POST", f"/review-cases/{cid}/resolve",
                      {"action": "APPROVE", "note": "verified it"}).status_code == 200
        assert [x.outcome for x in audit_rows(env, "REAUTHENTICATION", r.email)] == ["FAILURE", "SUCCESS"]

    def test_reauthentication_expires(self, env):
        r = env.account("rev@example.com", "REVIEWER")
        cid = claimed_by(r)
        r.age_session(created_minutes=60, idle_minutes=1, reauth_minutes=settings.REAUTH_WINDOW_MINUTES + 1)
        assert r.call("POST", f"/review-cases/{cid}/dismiss", {"note": "duplicate"}).json()["detail"]["code"] \
            == "REAUTH_REQUIRED"

    def test_repeated_wrong_passwords_end_the_session(self, env):
        r = env.account("rev@example.com", "REVIEWER")
        codes = [r.call("POST", "/auth/reauthenticate", {"password": "nope"}).status_code for _ in range(5)]
        assert codes == [400, 400, 400, 400, 401]
        assert r.call("GET", "/review-cases").status_code == 401

    def test_admin_sensitive_actions_need_a_recent_sign_in(self, env):
        admin = env.account("admin@example.com", "ADMIN")
        r = env.account("rev@example.com", "REVIEWER")
        cid = new_case()
        admin.age_session(created_minutes=settings.REAUTH_WINDOW_MINUTES + 5, idle_minutes=1)
        for method, path, body in (("POST", f"/review-cases/{cid}/assign", {"reviewer_email": r.email}),
                                   ("POST", f"/review-cases/{cid}/grants", {"reviewer_email": r.email}),
                                   ("PATCH", f"/admin/users/{r.farmer_id}/reviewer-approval", {"approved": False})):
            resp = admin.call(method, path, body)
            assert resp.status_code == 403 and resp.json()["detail"]["code"] == "REAUTH_REQUIRED", path
        assert env.auth.farmers[r.pk].reviewer_approved_at is not None
        admin.call("POST", "/auth/reauthenticate", {"password": PASSWORD})
        assert admin.call("POST", f"/review-cases/{cid}/assign", {"reviewer_email": r.email}).status_code == 200

    def test_reauthentication_requires_a_session_and_csrf(self, env):
        r = env.account("rev@example.com", "REVIEWER")
        assert TestClient(app).post("/auth/reauthenticate", json={"password": PASSWORD}).status_code == 401
        assert r.call("POST", "/auth/reauthenticate", {"password": PASSWORD}, csrf=False).status_code == 403


# ─── auditing of access ──────────────────────────────────────────────────────

class TestAccessAudit:
    def test_views_and_state_changes_are_audited(self, env):
        r = env.account("rev@example.com", "REVIEWER")
        cid = claimed_by(r)
        r.call("GET", "/review-cases", {"status": "IN_REVIEW"})
        r.call("GET", f"/review-cases/{cid}")
        r.call("POST", f"/review-cases/{cid}/resolve", {"action": "APPROVE", "note": "verified it"})
        actions = [(x.action, x.outcome) for x in audit_rows(env, actor=r.email)]
        assert ("REVIEW_ASSIGNED", "SUCCESS") in actions and ("REVIEW_APPROVE", "SUCCESS") in actions
        assert ("REVIEW_CASE_VIEWED", "SUCCESS") in actions and ("REVIEW_QUEUE_VIEWED", "SUCCESS") in actions
        viewed = audit_rows(env, "REVIEW_CASE_VIEWED", r.email)[0]
        assert viewed.target_id == cid and viewed.details["access"] == "assigned"
        queue = audit_rows(env, "REVIEW_QUEUE_VIEWED", r.email)[-1]
        assert queue.details["status"] == "IN_REVIEW" and queue.details["returned"] == 1
