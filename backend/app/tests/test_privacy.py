"""
Privacy and data settings (docs/PRIVACY.md): the published inventory matches what is stored,
disclosures don't claim external processing is local, consent and its withdrawal, export,
deletion by category and of the whole account, that one farmer can never see or delete another
farmer's data, and the API rules (sign-in, CSRF, recent sign-in, password + typed confirmation,
last administrator). Through the real HTTP API with real cookie sessions; in-memory stores stand
in for PostgreSQL (the SQL itself is covered by test_privacy_pg.py).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core import privacy
from app.core.config import settings
from app.database.repositories.privacy_repository import LastAdmin
from app.database.repositories.profile_repository import PROFILE_COLUMNS
from app.main import app
from app.services import notification_service, privacy_service, profile_service, review_service
from app.services import review_workflow as wf
from app.tests.test_rbac import User, env  # noqa: F401  (the RBAC environment fixture)
from app.tests.test_review_workflow import escalate


class FakePrivacyRepo:
    """privacy_repository over the in-memory stores, with the same scope and transaction semantics."""

    LastAdmin = LastAdmin

    def __init__(self, env):
        self.env = env

    @property
    def stores(self):
        return (profile_service.profile_repo, profile_service.history_repo, self.env.saved, notification_service.repo)

    async def sessions(self, pk):
        return [{"created_at": s.created_at, "last_seen_at": s.last_seen_at, "expires_at": s.expires_at,
                 "revoked_at": s.revoked_at, "revoked_reason": s.revoked_reason, "ip_address": s.ip_address}
                for s in self.env.auth.sessions.values() if s.farmer_id == pk]

    async def delete_profile(self, pk, actor):
        prof, history, _, _ = self.stores
        out = {"profile": 1 if prof.rows.pop(pk, None) else 0, "search_history": await history.clear(pk)}
        self.env.audit.add(actor, "PROFILE_DELETED", "account", actor.farmer_id, out)
        return out

    async def delete_saved_schemes(self, pk, actor):
        saved = self.env.saved
        ids = [i for i, r in saved.saved.items() if r.farmer_id == pk]
        items = [i for i, it in saved.items.items() if it.farmer_id == pk]
        for i in ids:
            del saved.saved[i]
        for i in items:
            del saved.items[i]
        out = {"saved_schemes": len(ids), "checklist_items": len(items)}
        self.env.audit.add(actor, "SAVED_SCHEMES_DELETED", "account", actor.farmer_id, out)
        return out

    async def delete_notification_data(self, pk, actor):
        n = notification_service.repo
        out = {"notification_preferences": 1 if n.prefs.pop(pk, None) is not None else 0,
               "scheme_subscriptions": len([s for s in n.subs if s[0] == pk]),
               "notifications": len([x for x in n.notifications.values() if x["farmer_id"] == pk])}
        n.subs = {s for s in n.subs if s[0] != pk}
        n.notifications = {k: v for k, v in n.notifications.items() if v["farmer_id"] != pk}
        out["phone"] = 1 if self.env.auth.farmers[pk].phone else 0
        self.env.auth._update(pk, phone=None, phone_verified_at=None)
        self.env.audit.add(actor, "NOTIFICATION_DATA_DELETED", "account", actor.farmer_id, out)
        return out

    async def delete_account(self, pk, actor):
        auth = self.env.auth
        me = auth.farmers.get(pk)
        if me is None:
            return {"deleted": False}
        if me.role == "ADMIN" and me.is_active and sum(1 for f in auth.farmers.values()
                                                       if f.role == "ADMIN" and f.is_active) <= 1:
            raise LastAdmin()
        threads = []
        for c in review_service._review_cases.values():
            if c.farmer_pk == pk:
                c.query, c.profile_snapshot, c.farmer_pk = "", {}, None
                threads.append(c.session_id)
            if c.assignee == me.email and c.status.value in ("PENDING", "IN_REVIEW"):
                c.assignee, c.status = None, review_service.ReviewStatus.PENDING
        await self.delete_profile(pk, actor)
        await self.delete_saved_schemes(pk, actor)
        await self.delete_notification_data(pk, actor)
        await auth.revoke_all_sessions(pk, "account_deleted")
        auth.sessions = {k: s for k, s in auth.sessions.items() if s.farmer_id != pk}
        del auth.farmers[pk]
        self.env.audit.add(actor, "ACCOUNT_DELETED", "account", me.farmer_id, {})
        return {"deleted": True, "counts": {"review_cases_anonymised": len(threads)}, "chat_threads": threads}


@pytest.fixture
def penv(env, monkeypatch):                     # noqa: F811
    monkeypatch.setattr(privacy_service, "repo", FakePrivacyRepo(env))
    return env


def fill(u: User, env):
    """Give an account data in every category."""
    assert u.call("PUT", "/farmers/me/profile", {"state": "KA", "age": 41, "category": "SC",
                                                 "primary_crop": "ragi", "consent_given": True}).status_code == 200
    asyncio.run(profile_service.record_search(u.farmer_id, f"schemes for {u.email}", 3, "en"))
    assert u.call("POST", "/farmers/me/saved-schemes", {"scheme_id": "PM_KISAN"}).status_code in (200, 201)
    assert u.call("PUT", "/farmers/me/subscriptions/PM_KISAN").status_code in (200, 201)
    env.auth._update(u.pk, phone="+919876543210", phone_verified_at=datetime.now(timezone.utc))
    case = asyncio.run(escalate(session=f"chat-{u.pk}"))
    asyncio.run(wf.link_farmer(case["case_id"], u.pk))
    return case["case_id"]


def export(u: User):
    r = u.call("GET", "/farmers/me/data/export")
    assert r.status_code == 200, r.text
    assert r.headers["Content-Disposition"].startswith("attachment") and r.headers["Cache-Control"].startswith("no-store")
    return r.json()


# ─── the published inventory ─────────────────────────────────────────────────

class TestInventory:
    def test_every_stored_profile_column_is_documented(self):
        documented = {c for f in privacy.PROFILE_FIELDS for c in f["columns"]}
        assert set(PROFILE_COLUMNS) <= documented, set(PROFILE_COLUMNS) - documented
        assert all(f["why"] and "required" in f for f in privacy.PROFILE_FIELDS + privacy.ACCOUNT_FIELDS)

    def test_required_and_optional_are_distinguished(self):
        required = {f["field"] for f in privacy.ACCOUNT_FIELDS + privacy.PROFILE_FIELDS if f["required"]}
        assert required == {"email", "password", "consent"}            # every profile detail is optional

    def test_disclosures_match_what_is_actually_sent(self):
        from app.utils.privacy import LLM_SAFE_PROFILE_FIELDS
        sent_to_llm = {f["field"] for f in privacy.PROFILE_FIELDS if privacy.GROQ in f["shared_with"]}
        safe = {"land_size" if f == "land_size_acres" else f for f in LLM_SAFE_PROFILE_FIELDS}
        assert safe <= sent_to_llm                                     # nothing sent is undisclosed
        # the web-search query is built from state and crop only (app/retrieval/web_retriever.py)
        assert {f["field"] for f in privacy.PROFILE_FIELDS if privacy.TAVILY in f["shared_with"]} == \
            {"state", "primary_crop"}

    def test_external_processing_is_never_described_as_local(self):
        text = str(privacy.policy()).lower()
        for claim in ("fully local", "never leaves", "processed locally", "all data stays", "on-device"):
            assert claim not in text
        assert {p["id"] for p in privacy.PROCESSORS} == {"groq", "tavily", "sarvam", "email_provider", "sms_provider"}
        assert "full text" in privacy.CHAT_NOTE.lower() or "anything you type" in privacy.CHAT_NOTE.lower()

    def test_policy_is_public_and_holds_no_personal_data(self, penv):
        r = TestClient(app).get("/privacy/policy")
        assert r.status_code == 200 and r.json()["retention_days"]["search_history"] == 90
        assert "@" not in str(r.json()["profile_fields"])


# ─── consent ─────────────────────────────────────────────────────────────────

class TestConsent:
    def test_nothing_is_saved_without_consent(self, penv):
        u = User(penv, "FARMER")
        r = u.call("PUT", "/farmers/me/profile", {"state": "KA"})
        assert r.status_code == 403 and r.json()["detail"]["code"] == "CONSENT_REQUIRED"
        assert profile_service.profile_repo.rows == {}
        assert asyncio.run(profile_service.record_search(u.farmer_id, "q", 1, "en")) is False

    def test_withdrawing_consent_deletes_the_profile_and_stops_recording(self, penv):
        u = User(penv, "FARMER")
        fill(u, penv)
        assert u.call("GET", "/farmers/me/data").json()["consent_given"] is True
        r = u.call("DELETE", "/farmers/me/profile")
        assert r.status_code == 200 and r.json()["deleted"] == {"profile": 1, "search_history": 1}
        assert u.call("GET", "/farmers/me/profile").status_code == 404
        assert asyncio.run(profile_service.record_search(u.farmer_id, "later search", 1, "en")) is False
        from app.services.chat_profile_service import load_saved_chat_profile
        assert asyncio.run(load_saved_chat_profile(u.farmer_id)) == ({}, False)   # chat no longer uses it
        data = u.call("GET", "/farmers/me/data").json()
        assert data["has_profile"] is False and data["consent_given"] is False
        assert data["counts"]["saved_schemes"] == 1                                # other categories untouched


# ─── view and export ─────────────────────────────────────────────────────────

class TestExport:
    def test_summary_and_export_contain_everything_of_mine_only(self, penv):
        a, b = User(penv, "FARMER"), User(penv, "FARMER")
        fill(a, penv)
        fill(b, penv)
        s = a.call("GET", "/farmers/me/data").json()
        assert s["counts"]["search_history"] == 1 and s["counts"]["saved_schemes"] == 1
        assert s["counts"]["followed_schemes"] == 1 and s["counts"]["review_cases"] == 1 and s["has_phone"]
        data = export(a)
        assert data["account"]["email"] == a.email and data["profile"]["age"] == 41
        assert data["search_history"][0]["query"] == f"schemes for {a.email}"
        assert data["saved_schemes"][0]["scheme_id"] == "PM_KISAN" and data["followed_schemes"]
        assert data["review_cases"][0]["open"] is True and data["sessions"] and data["errors"] == {}
        text = str(data)
        assert b.email not in text                                                  # nothing of b
        for secret in ("password_hash", "h$KisanPass123", "session_hash", "csrf"):
            assert secret not in text
        assert any(r.action == "DATA_EXPORTED" and r.actor_label == a.email for r in penv.audit.rows)

    def test_export_needs_a_recent_sign_in_and_is_rate_limited(self, penv):
        u = User(penv, "FARMER")
        s = max((x for x in penv.auth.sessions.values() if x.farmer_id == u.pk), key=lambda x: x.id)
        penv.auth.sessions[s.id] = s.model_copy(update={"created_at": datetime.now(timezone.utc) - timedelta(hours=1)})
        r = u.call("GET", "/farmers/me/data/export")
        assert r.status_code == 403 and r.json()["detail"]["code"] == "REAUTH_REQUIRED"
        assert u.call("POST", "/auth/reauthenticate", {"password": "KisanPass123"}).status_code == 200
        codes = [u.call("GET", "/farmers/me/data/export").status_code for _ in range(6)]
        assert codes == [200] * 5 + [429]


# ─── deletion by category ────────────────────────────────────────────────────

class TestCategoryDeletion:
    def test_saved_schemes_and_notification_data(self, penv):
        u = User(penv, "FARMER")
        fill(u, penv)
        r = u.call("DELETE", "/farmers/me/saved-schemes")
        assert r.status_code == 200 and r.json()["deleted"]["saved_schemes"] == 1
        assert r.json()["deleted"]["checklist_items"] > 0
        assert u.call("GET", "/farmers/me/saved-schemes").json() == []
        r = u.call("DELETE", "/farmers/me/notification-data")
        assert r.status_code == 200 and r.json()["deleted"]["scheme_subscriptions"] == 1
        assert r.json()["deleted"]["phone"] == 1 and penv.auth.farmers[u.pk].phone is None
        assert u.call("GET", "/farmers/me/subscriptions").json() == []
        actions = [x.action for x in penv.audit.rows if x.actor_label == u.email]
        assert "SAVED_SCHEMES_DELETED" in actions and "NOTIFICATION_DATA_DELETED" in actions

    def test_deletes_need_csrf_and_a_session(self, penv):
        u = User(penv, "FARMER")
        fill(u, penv)
        for path in ("/farmers/me/profile", "/farmers/me/saved-schemes", "/farmers/me/notification-data"):
            assert u.call("DELETE", path, csrf=False).status_code == 403
            assert TestClient(app).delete(path).status_code == 401
        assert profile_service.profile_repo.rows.get(u.pk) is not None


# ─── account deletion ────────────────────────────────────────────────────────

class TestAccountDeletion:
    def test_everything_goes_and_the_session_ends(self, penv):
        a, b = User(penv, "FARMER"), User(penv, "FARMER")
        case_a = fill(a, penv)
        case_b = fill(b, penv)
        from app.graph.workflow import memory
        memory.storage[f"chat-{a.pk}"] = {"x": 1}                          # the conversation in server memory
        r = a.call("POST", "/farmers/me/delete-account", {"password": "KisanPass123", "confirm": "delete my account"})
        assert r.status_code == 200 and r.json()["deleted"] is True
        assert r.json()["chat_conversations_cleared"] == 1 and f"chat-{a.pk}" not in memory.storage
        assert "Security record (audit log)" in r.json()["still_kept"]
        assert a.pk not in penv.auth.farmers
        assert a.call("GET", "/farmers/me/data").status_code == 401                # signed out everywhere
        assert profile_service.profile_repo.rows.get(a.pk) is None
        assert not [x for x in profile_service.history_repo.rows if x.farmer_id == a.pk]
        assert not [x for x in penv.saved.saved.values() if x.farmer_id == a.pk]
        anon = review_service.get_case(case_a)
        assert (anon.farmer_pk, anon.query, anon.profile_snapshot) == (None, "", {})
        # b is untouched
        assert profile_service.profile_repo.rows.get(b.pk) is not None
        assert review_service.get_case(case_b).farmer_pk == b.pk
        assert b.call("GET", "/farmers/me/data").json()["counts"]["saved_schemes"] == 1
        deleted = next(x for x in penv.audit.rows if x.action == "ACCOUNT_DELETED")
        assert deleted.actor_label == f"account:{a.farmer_id}" and a.email not in str(deleted)

    @pytest.mark.parametrize("body,code", [
        ({"password": "wrong-password", "confirm": "DELETE MY ACCOUNT"}, 400),
        ({"password": "KisanPass123", "confirm": "delete"}, 422),
        ({"password": "KisanPass123"}, 422),
        ({"password": "KisanPass123", "confirm": "DELETE MY ACCOUNT", "farmer_id": "someone-else"}, 422),
    ])
    def test_needs_password_and_typed_confirmation(self, penv, body, code):
        u = User(penv, "FARMER")
        assert u.call("POST", "/farmers/me/delete-account", body).status_code == code
        assert u.pk in penv.auth.farmers

    def test_needs_csrf_and_a_session(self, penv):
        u = User(penv, "FARMER")
        body = {"password": "KisanPass123", "confirm": "DELETE MY ACCOUNT"}
        assert u.call("POST", "/farmers/me/delete-account", body, csrf=False).status_code == 403
        assert TestClient(app).post("/farmers/me/delete-account", json=body).status_code == 401
        assert u.pk in penv.auth.farmers

    def test_last_administrator_cannot_delete_their_account(self, penv):
        admin = User(penv, "ADMIN")
        r = admin.call("POST", "/farmers/me/delete-account", {"password": "KisanPass123", "confirm": "DELETE MY ACCOUNT"})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "LAST_ADMIN"
        other = User(penv, "ADMIN")
        assert other.call("POST", "/farmers/me/delete-account",
                          {"password": "KisanPass123", "confirm": "DELETE MY ACCOUNT"}).status_code == 200

    def test_a_deleted_reviewers_open_cases_go_back_to_the_queue(self, penv):
        r = User(penv, "REVIEWER")
        case = asyncio.run(escalate(session="rv"))
        assert r.call("POST", f"/review-cases/{case['case_id']}/claim").status_code == 200
        r.call("POST", "/farmers/me/delete-account", {"password": "KisanPass123", "confirm": "DELETE MY ACCOUNT"})
        c = review_service.get_case(case["case_id"])
        assert c.assignee is None and c.status.value == "PENDING"


# ─── one farmer can never see or delete another farmer's data ────────────────

class TestIsolation:
    def test_no_route_takes_another_account(self, penv):
        a, b = User(penv, "FARMER"), User(penv, "FARMER")
        fill(b, penv)
        for path in ("/farmers/me/data", "/farmers/me/data/export"):
            r = a.call("GET", path + f"?farmer_id={b.farmer_id}")
            assert r.status_code == 200 and b.email not in r.text
        a.call("DELETE", f"/farmers/me/profile?farmer_id={b.farmer_id}")
        a.call("DELETE", f"/farmers/me/saved-schemes?farmer_id={b.farmer_id}")
        assert profile_service.profile_repo.rows.get(b.pk) is not None
        assert b.call("GET", "/farmers/me/data").json()["counts"]["saved_schemes"] == 1
        paths = [getattr(rt, "path", "") for rt in app.routes]
        assert not any(p.startswith("/farmers/") and "{farmer" in p for p in paths)

    def test_staff_cannot_read_a_farmers_data_either(self, penv):
        f = User(penv, "FARMER")
        fill(f, penv)
        for role in ("ADMIN", "REVIEWER"):
            staff = User(penv, role)
            data = staff.call("GET", "/farmers/me/data").json()
            assert data["has_profile"] is False and f.email not in str(data)       # their own (empty) data
            assert staff.call("GET", f"/admin/users/{f.farmer_id}").json().get("email") in (None, f.email)

    def test_retention_purge_uses_the_configured_rules(self, monkeypatch):
        seen = {}

        async def fake_purge(*args):
            seen["args"] = args
            return {"auth_sessions": 0}
        monkeypatch.setattr(privacy_service.repo, "purge_expired", fake_purge)
        asyncio.run(privacy_service.purge())
        assert seen["args"] == (settings.RETENTION_SESSION_DAYS, settings.RETENTION_TOKEN_DAYS,
                                settings.RETENTION_NOTIFICATION_DAYS, settings.RETENTION_REVIEW_CASE_DAYS, 90)
