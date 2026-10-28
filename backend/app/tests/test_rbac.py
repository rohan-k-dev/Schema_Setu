"""
Role-based access control (docs/RBAC.md) through the real HTTP API with real cookie
sessions: every protected endpoint × every role (FARMER, REVIEWER, ADMIN) plus
unauthenticated callers, deny-by-default route coverage, IDOR attempts, privilege
escalation, the shared review key, service-level checks and the audit trail.

The EXPECTED table below is written independently of app/core/permissions.py on
purpose: changing who may do what must change this test too. In-memory stores
stand in for PostgreSQL; the SQL is covered by test_rbac_pg.py.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.permissions import (
    Permission, PermissionDenied, Principal, ROLE_PERMISSIONS, Role, authorize, permissions_for,
)
from app.core.rate_limit import limiter
from app.database.repositories import audit_repository
from app.database.repositories.admin_repository import AdminRejected
from app.main import app
from app.models.db import SchemeRow
from app.models.db.farmer_auth import AuditEventRow
from app.models.review import ReviewAction, ReviewReason, ReviewStatus
from app.services import admin_service, review_service
from app.tests.fake_auth_repo import FakeAuthRepo
from app.tests.fake_ops import FakeAudit, FakeOpsRepo
from app.tests.test_dashboard import FakeCorpus, FakeHistoryRepo
from app.tests.test_profile_module import ORIGIN, UA, FakeProfileRepo
from app.tests.test_saved_schemes import FakeSavedRepo

ALL = {"FARMER", "REVIEWER", "ADMIN"}
NO_JOB = "00000000-0000-0000-0000-000000000000"


# ─── in-memory stand-ins ──────────────────────────────────────────────────────

class FakeAdminRepo:
    """admin_repository with the same rules: no self change, keep one active admin, revoke, audit."""

    def __init__(self, auth: FakeAuthRepo, audit: FakeAudit):
        self.auth, self.audit = auth, audit
        self.schemes = {"PM_KISAN": SchemeRow(id=1, scheme_id="PM_KISAN", name="PM-KISAN", description="d")}

    def _by_fid(self, fid):
        return next((f for f in self.auth.farmers.values() if f.farmer_id == fid), None)

    def _admins(self):
        return sum(1 for f in self.auth.farmers.values() if f.role == "ADMIN" and f.is_active)

    async def list_accounts(self, limit, offset, role=None, query=None):
        rows = [f for f in self.auth.farmers.values() if (role is None or f.role == role)
                and (query is None or query.lower() in f.email)]
        return rows[offset:offset + limit], len(rows)

    async def get_account(self, fid):
        return self._by_fid(fid)

    async def set_role(self, actor, fid, role, expected):
        t = self._by_fid(fid)
        if t is None:
            raise AdminRejected("NOT_FOUND", "Account not found.")
        if t.id == actor.account_pk:
            raise AdminRejected("SELF_CHANGE", "self")
        if expected is not None and t.role != expected.value:
            raise AdminRejected("CONFLICT", "changed")
        if t.role == role.value:
            return t
        if t.role == "ADMIN" and t.is_active and self._admins() <= 1:
            raise AdminRejected("LAST_ADMIN", "last")
        self.auth._update(t.id, role=role.value, reviewer_approved_at=None, reviewer_approved_by=None)
        await self.auth.revoke_all_sessions(t.id, "role_changed")
        self.audit.add(actor, "ROLE_CHANGED", "account", fid, {"from": t.role, "to": role.value})
        return self.auth.farmers[t.id]

    async def set_reviewer_approval(self, actor, fid, approved):
        t = self._by_fid(fid)
        if t is None:
            raise AdminRejected("NOT_FOUND", "Account not found.")
        if t.id == actor.account_pk:
            raise AdminRejected("SELF_CHANGE", "self")
        if t.role != "REVIEWER":
            raise AdminRejected("NOT_A_REVIEWER", "not a reviewer")
        if bool(t.reviewer_approved_at) == approved:
            return t
        from datetime import datetime, timezone
        self.auth._update(t.id, reviewer_approved_at=datetime.now(timezone.utc) if approved else None,
                          reviewer_approved_by=actor.label if approved else None)
        if not approved:
            await self.auth.revoke_all_sessions(t.id, "reviewer_approval_revoked")
        self.audit.add(actor, "REVIEWER_APPROVED" if approved else "REVIEWER_APPROVAL_REVOKED", "account", fid, {})
        return self.auth.farmers[t.id]

    async def set_active(self, actor, fid, active):
        t = self._by_fid(fid)
        if t is None:
            raise AdminRejected("NOT_FOUND", "Account not found.")
        if t.id == actor.account_pk:
            raise AdminRejected("SELF_CHANGE", "self")
        if t.is_active == active:
            return t
        if not active and t.role == "ADMIN" and self._admins() <= 1:
            raise AdminRejected("LAST_ADMIN", "last")
        self.auth._update(t.id, is_active=active)
        if not active:
            await self.auth.revoke_all_sessions(t.id, "account_deactivated")
        self.audit.add(actor, "ACCOUNT_REACTIVATED" if active else "ACCOUNT_DEACTIVATED", "account", fid, {})
        return self.auth.farmers[t.id]

    async def curate_scheme(self, actor, sid, changes):
        s = self.schemes.get(sid)
        if s is None:
            return None
        self.schemes[sid] = new = s.model_copy(update=changes)
        self.audit.add(actor, "SCHEME_CURATED", "scheme", sid,
                       {"before": {c: getattr(s, c) for c in changes}, "after": changes})
        return new


class User:
    """A signed-in account with its own browser (cookie jar) and CSRF token."""

    _n = itertools.count(1)

    def __init__(self, env, role: str):
        self.env = env
        self.email = f"{role.lower()}{next(self._n)}@example.com"
        self.c = TestClient(app, headers={"User-Agent": UA, "Origin": ORIGIN})
        assert self.c.post("/auth/register", json={"email": self.email, "password": "KisanPass123"}).status_code == 202
        self.pk = next(f.id for f in env.auth.farmers.values() if f.email == self.email)
        env.auth._update(self.pk, is_verified=True, role=role)
        if role == "REVIEWER":                       # approved by an administrator (docs/HUMAN_REVIEW.md)
            env.auth._update(self.pk, reviewer_approved_at=datetime.now(timezone.utc), reviewer_approved_by="admin")
        self.login()

    def login(self):
        r = self.c.post("/auth/login", json={"email": self.email, "password": "KisanPass123"})
        assert r.status_code == 200, r.text
        self.csrf = r.json()["csrf_token"]
        self.farmer_id = r.json()["user"]["farmer_id"]
        return r

    def call(self, method, path, body=None, csrf=True, headers=None):
        h = dict(headers or {})
        if csrf and method != "GET":
            h["X-CSRF-Token"] = self.csrf
        return self.c.request(method, path, json=body, headers=h)


@pytest.fixture
def env(monkeypatch):
    auth = FakeAuthRepo()
    audit = FakeAudit()
    saved = FakeSavedRepo()
    saved.put_scheme("PM_KISAN")
    prof = FakeProfileRepo(auth)
    corpus, history = FakeCorpus(), FakeHistoryRepo()
    admin_repo = FakeAdminRepo(auth, audit)
    ops = FakeOpsRepo()
    from app.tests.fake_notifications import FakeChangeRepo, FakeNotificationRepo
    change_repo, notif_repo = FakeChangeRepo(), FakeNotificationRepo(auth, saved)

    async def pk_of(farmer_id):
        return next((f.id for f in auth.farmers.values() if f.farmer_id == farmer_id), None)

    async def no_saved(pk):
        return []

    for target, value in {
        "app.services.auth_service.repo": auth,
        # fast stand-ins for Argon2 (account security is tested in test_auth_security.py)
        "app.services.auth_service.hash_password": lambda p: "h$" + p,
        "app.services.auth_service.verify_password": lambda p, h: h == "h$" + p,
        "app.services.auth_service.password_needs_rehash": lambda h: False,
        "app.services.profile_service.profile_repo": prof,
        "app.services.profile_service.history_repo": history,
        "app.services.profile_service.get_farmer_pk": pk_of,
        "app.services.profile_service.get_saved_schemes": no_saved,
        "app.services.dashboard_service.SchemeRepository": corpus,
        "app.services.dashboard_service.RuleRepository": corpus,
        "app.services.saved_scheme_service.repo": saved,
        "app.services.saved_scheme_service.profile_repo": prof,
        "app.services.admin_service.repo": admin_repo,
        "app.services.admin_service.audit_repo": audit,
        "app.api.deps.audit_repo": audit,
        "app.services.ops_service.ops_repo": ops,
        "app.services.ops_service.audit_repo": audit,
        "app.services.admin_jobs.ops_repo": ops,
        "app.services.admin_jobs.audit_repo": audit,
        "app.services.scheme_update_service.changes_repo": change_repo,
        "app.services.scheme_update_service.notif_repo": notif_repo,
        "app.services.scheme_update_service.audit_repo": audit,
        "app.services.notification_service.repo": notif_repo,
        "app.services.notification_service.audit_repo": audit,
        "app.api.notifications.repo": notif_repo,
        "app.api.notifications.audit_repository": audit,
        "app.api.scheme_updates.notif_repo": notif_repo,
        "app.api.auth.is_db_available": lambda: True,
        "app.api.deps.is_db_available": lambda: True,
    }.items():
        monkeypatch.setattr(target, value)
    monkeypatch.setattr(audit_repository, "record", audit.record)       # review decisions
    for name in ("send_verification_email", "send_password_reset_email",
                 "send_account_exists_email", "send_password_changed_email"):
        async def _noop(*a, **k):
            return True
        monkeypatch.setattr(f"app.services.auth_service.email_service.{name}", _noop)
    monkeypatch.setattr(settings, "REVIEW_API_KEY", "dev-review-key-123")
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    monkeypatch.setattr(review_service, "_review_cases", {})
    monkeypatch.setattr(review_service, "_audit_log", [])
    limiter.reset()
    ns = SimpleNamespace(auth=auth, audit=audit, saved=saved, admin=admin_repo, ops=ops)
    ns.user = lambda role: User(ns, role)
    ns.case = lambda: review_service.create_review_case("s1", "q", ReviewReason.UNVERIFIABLE, {"state": "KA"},
                                                        ["X"], [], []).case_id
    yield ns
    limiter.reset()


# ─── the matrix ───────────────────────────────────────────────────────────────

# (method, path template, body, roles that may call it)
ENDPOINTS = [
    ("GET", "/auth/permissions", None, ALL),
    ("GET", "/farmers/me/dashboard", None, ALL),
    ("GET", "/farmers/me/profile", None, ALL),
    ("PUT", "/farmers/me/profile", {"state": "KA", "consent_given": True}, ALL),
    ("GET", "/farmers/me/saved-schemes", None, ALL),
    ("POST", "/farmers/me/saved-schemes", {"scheme_id": "PM_KISAN"}, ALL),
    ("GET", "/farmers/me/saved-schemes/PM_KISAN", None, ALL),
    ("PATCH", "/farmers/me/saved-schemes/PM_KISAN", {"notes": "n"}, ALL),
    ("DELETE", "/farmers/me/saved-schemes/PM_KISAN", None, ALL),
    ("PATCH", "/farmers/me/saved-schemes/PM_KISAN/checklist/1", {"completed": True}, ALL),
    ("POST", "/farmers/me/saved-schemes/PM_KISAN/checklist", {"label": "m"}, ALL),
    ("DELETE", "/farmers/me/saved-schemes/PM_KISAN/checklist/1", None, ALL),
    ("GET", "/farmers/me/search-history", None, ALL),
    ("DELETE", "/farmers/me/search-history/1", None, ALL),
    ("DELETE", "/farmers/me/search-history", None, ALL),
    ("GET", "/farmers/me/conversations", None, ALL),
    ("GET", "/farmers/me/conversations/no-such-thread", None, ALL),
    ("DELETE", "/farmers/me/conversations/no-such-thread", None, ALL),
    ("DELETE", "/farmers/me/conversations", None, ALL),
    ("GET", "/farmers/me/chat-history-settings", None, ALL),
    ("PUT", "/farmers/me/chat-history-settings", {"enabled": True}, ALL),
    ("GET", "/farmers/me/eligibility", None, ALL),
    ("GET", "/farmers/me/eligibility/basis", None, ALL),
    ("GET", "/review-cases", None, {"REVIEWER", "ADMIN"}),
    ("GET", "/review-cases/{case}", None, {"REVIEWER", "ADMIN"}),
    ("GET", "/review-cases/stats/summary", None, {"REVIEWER", "ADMIN"}),
    ("POST", "/review-cases/{case}/resolve", {"action": "REQUEST_INFORMATION"}, {"REVIEWER"}),
    ("POST", "/review-cases/{case}/dismiss", {}, {"REVIEWER"}),
    # reviewer dashboard workflow (docs/HUMAN_REVIEW.md)
    ("POST", "/review-cases/{case}/claim", {}, {"REVIEWER"}),
    ("POST", "/review-cases/{case}/release", {}, {"REVIEWER"}),
    ("POST", "/review-cases/{case}/comments", {"text": "checked the portal"}, {"REVIEWER"}),
    ("POST", "/review-cases/{case}/assign", {"reviewer_email": "nobody@example.com"}, {"ADMIN"}),
    # reviewer access policy (docs/HUMAN_REVIEW.md)
    ("POST", "/review-cases/{case}/grants", {"reviewer_email": "nobody@example.com"}, {"ADMIN"}),
    ("POST", "/review-cases/{case}/grants/revoke", {"reviewer_email": "nobody@example.com"}, {"ADMIN"}),
    ("PATCH", "/admin/users/{target}/reviewer-approval", {"approved": True}, {"ADMIN"}),
    ("GET", "/farmers/me/review-cases", None, ALL),
    # privacy and data settings (docs/PRIVACY.md) — own account only
    ("GET", "/farmers/me/data", None, ALL),
    ("GET", "/farmers/me/data/export", None, ALL),
    ("DELETE", "/farmers/me/profile", None, ALL),
    ("DELETE", "/farmers/me/saved-schemes", None, ALL),
    ("DELETE", "/farmers/me/notification-data", None, ALL),
    ("POST", "/farmers/me/delete-account", {"password": "wrong", "confirm": "no"}, ALL),
    ("GET", "/admin/users", None, {"ADMIN"}),
    ("GET", "/admin/users/{target}", None, {"ADMIN"}),
    ("PATCH", "/admin/users/{target}/role", {"role": "REVIEWER"}, {"ADMIN"}),
    ("PATCH", "/admin/users/{target}/status", {"is_active": False}, {"ADMIN"}),
    ("PATCH", "/admin/schemes/PM_KISAN", {"needs_review": True}, {"ADMIN"}),
    ("GET", "/admin/audit-events", None, {"ADMIN"}),
    ("GET", "/admin/audit-events/verify", None, {"ADMIN"}),
    ("GET", "/admin/ops/overview", None, {"ADMIN"}),
    ("GET", "/admin/ops/errors", None, {"ADMIN"}),
    ("GET", "/admin/ops/conflicts", None, {"ADMIN"}),
    ("GET", "/admin/ops/live-sources", None, {"ADMIN"}),
    ("POST", "/admin/ops/validate", None, {"ADMIN"}),
    ("GET", "/admin/ops/jobs", None, {"ADMIN"}),
    ("GET", f"/admin/ops/jobs/{NO_JOB}", None, {"ADMIN"}),
    ("POST", "/admin/ops/jobs", {"kind": "REBUILD_GRAPH", "reason": "matrix test"}, {"ADMIN"}),
    # notifications (own account) and scheme-update review (docs/SCHEME_UPDATES.md)
    ("GET", "/farmers/me/notifications", None, ALL),
    ("POST", "/farmers/me/notifications/1/read", None, ALL),
    ("POST", "/farmers/me/notifications/read-all", None, ALL),
    ("GET", "/farmers/me/notification-preferences", None, ALL),
    ("PUT", "/farmers/me/notification-preferences", {"in_app": True}, ALL),
    ("GET", "/farmers/me/subscriptions", None, ALL),
    ("PUT", "/farmers/me/subscriptions/PM_KISAN", None, ALL),
    ("DELETE", "/farmers/me/subscriptions/PM_KISAN", None, ALL),
    ("POST", "/farmers/me/phone", {"phone": "9876543210"}, ALL),
    ("POST", "/farmers/me/phone/verify", {"code": "123456"}, ALL),
    ("DELETE", "/farmers/me/phone", None, ALL),
    ("GET", "/admin/scheme-changes/sources", None, {"ADMIN"}),
    ("POST", "/admin/scheme-changes/detect", {"source": "none.json"}, {"ADMIN"}),
    ("GET", "/admin/scheme-changes/batches", None, {"ADMIN"}),
    ("GET", "/admin/scheme-changes", None, {"ADMIN"}),
    ("POST", "/admin/scheme-changes/1/review", {"decision": "REJECTED"}, {"ADMIN"}),
    ("POST", f"/admin/scheme-changes/batches/{NO_JOB}/discard", None, {"ADMIN"}),
    ("GET", "/admin/notifications/deliveries", None, {"ADMIN"}),
    ("POST", "/admin/notifications/dispatch", None, {"ADMIN"}),
]

PUBLIC = {
    "/", "/health", "/health/live", "/health/ready", "/chat", "/voice", "/tts", "/schemes",
    "/schemes/{scheme_id}", "/languages", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc",
    # account endpoints authenticate themselves (sign-in / session / password flows)
    "/auth/register", "/auth/verify-email", "/auth/resend-verification", "/auth/login", "/auth/session",
    "/auth/logout", "/auth/logout-all", "/auth/forgot-password", "/auth/reset-password",
    "/auth/change-password", "/auth/reauthenticate",
    "/privacy/policy",                      # public: what is collected and why (no personal data)
    # self-authenticating: a signed unsubscribe token / the SMS provider's HMAC signature
    "/notifications/unsubscribe", "/notifications/sms-status",
}

_TEMPLATE = {"/review-cases/{case}": "/review-cases/{case_id}",
             "/admin/users/{target}": "/admin/users/{farmer_id}",
             "/admin/users/{target}/role": "/admin/users/{farmer_id}/role",
             "/admin/users/{target}/status": "/admin/users/{farmer_id}/status",
             "/admin/users/{target}/reviewer-approval": "/admin/users/{farmer_id}/reviewer-approval",
             "/review-cases/{case}/resolve": "/review-cases/{case_id}/resolve",
             "/review-cases/{case}/dismiss": "/review-cases/{case_id}/dismiss",
             "/review-cases/{case}/claim": "/review-cases/{case_id}/claim",
             "/review-cases/{case}/release": "/review-cases/{case_id}/release",
             "/review-cases/{case}/comments": "/review-cases/{case_id}/comments",
             "/review-cases/{case}/assign": "/review-cases/{case_id}/assign",
             "/review-cases/{case}/grants": "/review-cases/{case_id}/grants",
             "/review-cases/{case}/grants/revoke": "/review-cases/{case_id}/grants/revoke"}


def _route_key(method, template):
    t = _TEMPLATE.get(template, template)
    for real, concrete in ((f"/admin/ops/jobs/{{job_id}}", f"/admin/ops/jobs/{NO_JOB}"),
                           ("/admin/scheme-changes/batches/{batch_id}", f"/admin/scheme-changes/batches/{NO_JOB}"),
                           ("/admin/scheme-changes/{change_id}", "/admin/scheme-changes/1"),
                           ("/farmers/me/notifications/{notification_id}", "/farmers/me/notifications/1"),
                           ("/farmers/me/subscriptions/{scheme_id}", "/farmers/me/subscriptions/PM_KISAN"),
                           ("/farmers/me/saved-schemes/{scheme_id}", "/farmers/me/saved-schemes/PM_KISAN"),
                           ("/admin/schemes/{scheme_id}", "/admin/schemes/PM_KISAN"),
                           ("/farmers/me/search-history/{entry_id}", "/farmers/me/search-history/1"),
                           ("/farmers/me/conversations/{thread_id}", "/farmers/me/conversations/no-such-thread")):
        t = t.replace(concrete, real)
    return method, t.replace("/checklist/1", "/checklist/{item_id}")


def _fill(template, env, target_id):
    return template.replace("{case}", env.case()).replace("{target}", target_id)


def _ids(e):
    return f"{e[0]} {e[1]}"


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=_ids)
@pytest.mark.parametrize("role", sorted(ALL))
def test_role_matrix(env, role, endpoint):
    method, template, body, allowed = endpoint
    me = env.user(role)
    other = env.user("FARMER")
    env.user("ADMIN")                          # a second admin: demoting / deactivating isn't "last admin"
    r = me.call(method, _fill(template, env, other.farmer_id), body)
    if role in allowed:
        # permitted: anything but a refusal or a crash (503 = e.g. SMS not configured is a valid answer)
        assert r.status_code not in (401, 403, 500), (role, endpoint, r.status_code, r.text)
    else:
        assert r.status_code == 403, (role, endpoint, r.status_code, r.text)
        assert r.json()["detail"]["code"] == "FORBIDDEN"
        if template.startswith("/admin/users/") and method == "PATCH":
            assert env.auth.farmers[other.pk].role == "FARMER" and env.auth.farmers[other.pk].is_active


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=_ids)
def test_unauthenticated_gets_401(env, endpoint):
    method, template, body, _ = endpoint
    target = env.user("FARMER")
    anon = TestClient(app, headers={"User-Agent": UA, "Origin": ORIGIN})
    r = anon.request(method, _fill(template, env, target.farmer_id), json=body)
    assert r.status_code == 401, (endpoint, r.status_code)


@pytest.mark.parametrize("endpoint", [e for e in ENDPOINTS if e[0] != "GET"], ids=_ids)
def test_state_changes_without_csrf_are_refused(env, endpoint):
    method, template, body, allowed = endpoint
    me = env.user(sorted(allowed)[0])
    other = env.user("FARMER")
    r = me.call(method, _fill(template, env, other.farmer_id), body, csrf=False)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "CSRF_FAILED"


def test_matrix_covers_every_protected_route_and_nothing_is_open_by_accident():
    """Deny by default: each non-public route declares a permission and is in the matrix."""
    def permissions_of(dependant):
        found = []
        for d in dependant.dependencies:
            if getattr(d.call, "required_permission", None) is not None:
                found.append(d.call.required_permission)
            found += permissions_of(d)
        return found

    def calls_of(dependant):
        return [d.call for d in dependant.dependencies] + [c for d in dependant.dependencies for c in calls_of(d)]

    from app.api.deps import get_current_principal
    signed_in_only = {"/auth/permissions"}            # reports the caller's own role; nothing else
    matrix = {_route_key(m, t) for m, t, _, _ in ENDPOINTS}
    for route in app.routes:
        path = getattr(route, "path", "")
        if path in PUBLIC or not hasattr(route, "dependant"):
            continue
        for method in route.methods - {"HEAD"}:
            if path in signed_in_only:
                assert get_current_principal in calls_of(route.dependant)
            else:
                assert permissions_of(route.dependant), f"{method} {path} has no permission check"
            assert (method, path) in matrix, f"{method} {path} is missing from the RBAC test matrix"


def test_expected_table_matches_the_permission_matrix_in_code():
    # The farmer's own data is the only thing every role shares.
    assert ROLE_PERMISSIONS[Role.FARMER] < ROLE_PERMISSIONS[Role.REVIEWER]
    assert Permission.REVIEW_CASE_DECIDE not in ROLE_PERMISSIONS[Role.ADMIN]        # separation of duties
    for p in (Permission.USER_READ, Permission.USER_ROLE_ASSIGN, Permission.USER_STATUS_MANAGE,
              Permission.AUDIT_READ, Permission.SCHEME_CURATE):
        assert [r for r in Role if p in ROLE_PERMISSIONS[r]] == [Role.ADMIN]
    assert permissions_for("SUPERUSER") == frozenset() and permissions_for(None) == frozenset()


# ─── privilege escalation ─────────────────────────────────────────────────────

class TestPrivilegeEscalation:
    def test_registration_cannot_choose_a_role(self, env):
        c = TestClient(app, headers={"User-Agent": UA, "Origin": ORIGIN})
        r = c.post("/auth/register", json={"email": "x@example.com", "password": "KisanPass123", "role": "ADMIN"})
        assert r.status_code == 422 and env.auth.farmers == {}
        c.post("/auth/register", json={"email": "x@example.com", "password": "KisanPass123"})
        assert next(iter(env.auth.farmers.values())).role == "FARMER"

    def test_profile_update_cannot_set_a_role(self, env):
        f = env.user("FARMER")
        assert f.call("PUT", "/farmers/me/profile", {"role": "ADMIN", "consent_given": True}).status_code == 422
        assert env.auth.farmers[f.pk].role == "FARMER"

    @pytest.mark.parametrize("role", ["FARMER", "REVIEWER"])
    def test_non_admin_cannot_change_own_or_other_roles(self, env, role):
        me, other = env.user(role), env.user("FARMER")
        for target in (me, other):
            assert me.call("PATCH", f"/admin/users/{target.farmer_id}/role", {"role": "ADMIN"}).status_code == 403
        assert env.auth.farmers[me.pk].role == role and env.auth.farmers[other.pk].role == "FARMER"

    def test_admin_cannot_change_own_role_or_deactivate_self(self, env):
        a, _ = env.user("ADMIN"), env.user("ADMIN")
        r = a.call("PATCH", f"/admin/users/{a.farmer_id}/role", {"role": "FARMER"})
        assert r.status_code == 403 and r.json()["detail"]["code"] == "SELF_CHANGE"
        r = a.call("PATCH", f"/admin/users/{a.farmer_id}/status", {"is_active": False})
        assert r.status_code == 403 and r.json()["detail"]["code"] == "SELF_CHANGE"
        assert env.auth.farmers[a.pk].role == "ADMIN" and env.auth.farmers[a.pk].is_active

    def test_last_active_admin_cannot_be_demoted_or_deactivated(self, env):
        a, b = env.user("ADMIN"), env.user("ADMIN")
        assert a.call("PATCH", f"/admin/users/{b.farmer_id}/role", {"role": "FARMER"}).status_code == 200
        b.login()                                                     # b is a farmer now
        assert b.call("PATCH", f"/admin/users/{a.farmer_id}/role", {"role": "FARMER"}).status_code == 403
        c = env.user("ADMIN")
        env.auth._update(c.pk, is_active=False)                       # an inactive admin doesn't count
        assert a.call("PATCH", f"/admin/users/{a.farmer_id}/role", {"role": "FARMER"}).status_code == 403
        r = env.admin.set_role                                        # direct repository call: last admin
        with pytest.raises(AdminRejected) as exc:
            import asyncio
            asyncio.run(r(Principal(role=None, label="cli", via="cli"), a.farmer_id, Role.FARMER, None))
        assert exc.value.code == "LAST_ADMIN"

    def test_role_change_applies_at_once_and_ends_the_targets_sessions(self, env):
        admin, f = env.user("ADMIN"), env.user("FARMER")
        assert f.call("GET", "/review-cases").status_code == 403
        r = admin.call("PATCH", f"/admin/users/{f.farmer_id}/role", {"role": "REVIEWER", "expected_role": "FARMER"})
        assert r.status_code == 200 and r.json()["role"] == "REVIEWER"
        assert f.call("GET", "/review-cases").status_code == 401          # old session revoked
        f.login()
        assert f.call("GET", "/review-cases").status_code == 403          # role alone: not approved yet
        r = admin.call("PATCH", f"/admin/users/{f.farmer_id}/reviewer-approval", {"approved": True})
        assert r.status_code == 200 and r.json()["reviewer_approved"] is True
        assert f.call("GET", "/review-cases").status_code == 200
        assert f.c.get("/auth/permissions").json()["role"] == "REVIEWER"
        r = admin.call("PATCH", f"/admin/users/{f.farmer_id}/role", {"role": "ADMIN", "expected_role": "FARMER"})
        assert r.status_code == 409                                       # stale expected_role

    def test_role_is_read_from_the_account_on_every_request(self, env):
        r = env.user("REVIEWER")
        assert r.call("GET", "/review-cases").status_code == 200
        env.auth._update(r.pk, role="FARMER")                            # changed in the database only
        assert r.call("GET", "/review-cases").status_code == 403

    def test_unknown_role_has_no_permissions(self, env):
        u = env.user("FARMER")
        env.auth._update(u.pk, role="SUPERUSER")
        for path in ("/farmers/me/profile", "/review-cases", "/admin/users"):
            assert u.call("GET", path).status_code == 403
        assert u.c.get("/auth/permissions").json() == {"role": "NONE", "permissions": []}

    def test_deactivated_account_is_locked_out(self, env):
        admin, f = env.user("ADMIN"), env.user("FARMER")
        assert admin.call("PATCH", f"/admin/users/{f.farmer_id}/status", {"is_active": False}).status_code == 200
        assert f.call("GET", "/farmers/me/profile").status_code == 401
        assert f.c.post("/auth/login", json={"email": f.email, "password": "KisanPass123"}).status_code == 403
        assert admin.call("PATCH", f"/admin/users/{f.farmer_id}/status", {"is_active": True}).status_code == 200
        assert f.login().status_code == 200

    def test_admin_requests_cannot_smuggle_extra_fields(self, env):
        a, f = env.user("ADMIN"), env.user("FARMER")
        for body in ({"role": "ROOT"}, {"role": "ADMIN", "farmer_id": a.farmer_id}, {"is_active": "yes"}):
            path = "role" if "role" in body else "status"
            assert a.call("PATCH", f"/admin/users/{f.farmer_id}/{path}", body).status_code == 422
        assert a.call("PATCH", "/admin/schemes/PM_KISAN", {"eligibility_rules": []}).status_code == 422
        assert env.auth.farmers[f.pk].role == "FARMER"


# ─── IDOR and scope ───────────────────────────────────────────────────────────

class TestScope:
    def test_no_self_service_route_accepts_an_account_id(self):
        for route in app.routes:
            path = getattr(route, "path", "")
            if path.startswith("/farmers"):
                assert path.startswith("/farmers/me/") and "{farmer" not in path

    def test_admin_account_view_has_no_profile_or_contact_data(self, env):
        a, f = env.user("ADMIN"), env.user("FARMER")
        f.call("PUT", "/farmers/me/profile", {"state": "KA", "age": 40, "consent_given": True})
        body = a.call("GET", f"/admin/users/{f.farmer_id}").json()
        assert set(body) == {"farmer_id", "email", "full_name", "role", "is_active", "is_verified", "locked",
                             "reviewer_approved", "created_at", "last_login_at"}
        assert a.call("GET", "/admin/users/not-an-account").status_code == 404

    def test_staff_own_data_is_still_only_their_own(self, env):
        f, r = env.user("FARMER"), env.user("REVIEWER")
        f.call("PUT", "/farmers/me/profile", {"state": "Punjab", "consent_given": True})
        f.call("POST", "/farmers/me/saved-schemes", {"scheme_id": "PM_KISAN"})
        assert r.call("GET", "/farmers/me/profile").status_code == 404           # reviewer has none
        assert r.call("GET", "/farmers/me/saved-schemes").json() == []
        item = f.call("GET", "/farmers/me/saved-schemes/PM_KISAN").json()["checklist"][0]["id"]
        r.call("POST", "/farmers/me/saved-schemes", {"scheme_id": "PM_KISAN"})
        assert r.call("PATCH", f"/farmers/me/saved-schemes/PM_KISAN/checklist/{item}",
                      {"completed": True}).status_code == 404                    # IDOR: f's item id

    def test_reviewer_scope_is_the_review_queue_only(self, env):
        r = env.user("REVIEWER")
        for path in ("/admin/users", "/admin/audit-events"):
            assert r.call("GET", path).status_code == 403
        assert r.call("PATCH", "/admin/schemes/PM_KISAN", {"status": "SUSPENDED"}).status_code == 403
        assert env.admin.schemes["PM_KISAN"].status == "ACTIVE"


# ─── review queue ─────────────────────────────────────────────────────────────

class TestReview:
    def test_decision_is_recorded_under_the_signed_in_reviewer(self, env):
        r = env.user("REVIEWER")
        cid = env.case()
        resp = r.call("POST", f"/review-cases/{cid}/resolve", {"action": "REQUEST_INFORMATION", "note": "n"})
        assert resp.status_code == 200 and resp.json()["case"]["reviewer_id"] == r.email
        assert r.call("GET", f"/review-cases/{cid}").json()["audit_log"][-1]["reviewer"] == r.email
        decision = next(e for e in env.audit.rows if e.action == "REVIEW_REQUEST_INFORMATION")
        assert decision.actor_label == r.email
        assert env.audit.rows[-1].action == "REVIEW_CASE_VIEWED" and env.audit.rows[-1].actor_label == r.email

    def test_reviewer_name_cannot_be_spoofed(self, env):
        r = env.user("REVIEWER")
        cid = env.case()
        resp = r.call("POST", f"/review-cases/{cid}/resolve", {"action": "APPROVE", "reviewer_id": "someone-else"})
        assert resp.status_code == 422 and review_service.get_case(cid).status == ReviewStatus.PENDING

    def test_admin_oversees_but_cannot_decide(self, env):
        a = env.user("ADMIN")
        cid = env.case()
        assert a.call("GET", f"/review-cases/{cid}").status_code == 200
        assert a.call("POST", f"/review-cases/{cid}/resolve", {"action": "APPROVE"}).status_code == 403
        assert review_service.get_case(cid).status == ReviewStatus.PENDING

    def test_dev_review_key_is_limited_to_review_and_off_in_production(self, env, monkeypatch):
        c = TestClient(app, headers={"User-Agent": UA})
        key = {"X-Review-Key": "dev-review-key-123"}
        cid = env.case()
        assert c.get("/review-cases", headers=key).status_code == 200
        r = c.post(f"/review-cases/{cid}/resolve", json={"action": "REQUEST_INFORMATION"}, headers=key)
        assert r.status_code == 200 and r.json()["case"]["reviewer_id"] == "review-key"
        for path in ("/admin/users", "/farmers/me/profile", "/admin/audit-events"):
            assert c.get(path, headers=key).status_code == 401           # the key is not an account
        assert c.get("/review-cases", headers={"X-Review-Key": "guess"}).status_code == 403
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        assert c.get("/review-cases", headers=key).status_code == 403
        monkeypatch.setattr(settings, "ENVIRONMENT", "development")
        monkeypatch.setattr(settings, "REVIEW_API_KEY", None)
        assert c.get("/review-cases", headers=key).status_code == 403

    def test_farmer_session_plus_wrong_key_does_not_fall_back(self, env):
        f = env.user("FARMER")
        assert f.call("GET", "/review-cases", headers={"X-Review-Key": "guess"}).status_code == 403


# ─── service-level checks (defence in depth) ──────────────────────────────────

def _p(role: Role, pk=99) -> Principal:
    return Principal(role=role, label=f"{role.value}@x", account_pk=pk, farmer_id=f"uuid-{pk}",
                     permissions=permissions_for(role))


class TestServiceLevel:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("role", [Role.FARMER, Role.REVIEWER])
    async def test_admin_services_refuse_non_admins(self, env, role):
        from app.models.rbac_schemas import RoleChangeRequest, SchemeCurationRequest
        for call in (admin_service.list_users(_p(role), 10, 0),
                     admin_service.get_user(_p(role), "uuid-1"),
                     admin_service.change_role(_p(role), "uuid-1", RoleChangeRequest(role=Role.ADMIN)),
                     admin_service.change_status(_p(role), "uuid-1", False),
                     admin_service.curate_scheme(_p(role), "PM_KISAN", SchemeCurationRequest(status="SUSPENDED")),
                     admin_service.list_audit_events(_p(role), 10, 0)):
            with pytest.raises(PermissionDenied):
                await call

    @pytest.mark.asyncio
    async def test_review_services_enforce_read_and_decide(self, env):
        cid = env.case()
        for fn in (lambda p: review_service.list_cases_for(p), lambda p: review_service.get_case_for(p, cid),
                   lambda p: review_service.queue_stats_for(p)):
            with pytest.raises(PermissionDenied):
                fn(_p(Role.FARMER))
            fn(_p(Role.ADMIN))
        with pytest.raises(PermissionDenied):
            await review_service.resolve_case_as(_p(Role.ADMIN), cid, ReviewAction.APPROVE)
        with pytest.raises(PermissionDenied):
            await review_service.dismiss_case_as(None, cid)
        assert review_service.get_case(cid).status == ReviewStatus.PENDING

    def test_own_data_permission_needs_an_account(self):
        with pytest.raises(PermissionDenied):
            authorize(Principal.review_key(), Permission.PROFILE_OWN_READ)
        with pytest.raises(PermissionDenied):
            authorize(Principal(role=Role.FARMER, label="x", permissions=permissions_for(Role.FARMER)),
                      Permission.PROFILE_OWN_READ)


# ─── audit trail ──────────────────────────────────────────────────────────────

class TestAudit:
    def test_admin_actions_and_denied_attempts_are_audited(self, env):
        a, f = env.user("ADMIN"), env.user("FARMER")
        env.user("ADMIN")
        a.call("PATCH", f"/admin/users/{f.farmer_id}/role", {"role": "REVIEWER"})
        a.call("PATCH", "/admin/schemes/PM_KISAN", {"status": "SUSPENDED", "review_notes": "wrong amount"})
        f.login()
        assert f.call("GET", "/admin/users").status_code == 403
        actions = [(e.action, e.actor_label) for e in env.audit.rows]
        assert ("ROLE_CHANGED", a.email) in actions and ("SCHEME_CURATED", a.email) in actions
        denied = [e for e in env.audit.rows if e.action == "ACCESS_DENIED"]
        assert denied[-1].actor_label == f.email and denied[-1].target_id == "GET /admin/users"
        assert denied[-1].details == {"permission": "users:read"}

        page = a.call("GET", "/admin/audit-events?action=ROLE_CHANGED").json()
        assert page["total"] == 1 and page["items"][0]["details"] == {"from": "FARMER", "to": "REVIEWER"}
        curated = a.call("GET", "/admin/audit-events?target_type=scheme&target_id=PM_KISAN").json()["items"][0]
        assert curated["details"]["before"] == {"status": "ACTIVE", "review_notes": None}

    def test_no_route_can_change_or_delete_audit_events(self):
        for route in app.routes:
            if "audit" in getattr(route, "path", ""):
                assert route.methods <= {"GET", "HEAD"}

    def test_scheme_curation_cannot_touch_rules(self, env):
        a = env.user("ADMIN")
        r = a.call("PATCH", "/admin/schemes/PM_KISAN", {"status": "SUSPENDED"})
        assert r.status_code == 200 and r.json()["status"] == "SUSPENDED" and "re-import" in r.json()["note"]
        assert a.call("PATCH", "/admin/schemes/PM_KISAN", {}).status_code == 422
        assert a.call("PATCH", "/admin/schemes/PM_KISAN", {"status": None}).status_code == 422
        assert a.call("PATCH", "/admin/schemes/NOPE", {"needs_review": True}).status_code == 404
