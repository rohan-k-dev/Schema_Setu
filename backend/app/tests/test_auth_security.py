"""
Account security tests: registration, login, server-managed
cookie sessions, CSRF, logout, password reset / change, lockout, rate limiting
and session-hijacking attempts — through the real HTTP API with an in-memory
account store (FakeAuthRepo). The PostgreSQL repository itself is covered by
test_auth_repository_pg.py.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import bcrypt
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.rate_limit import limiter
from app.core.security import (
    csrf_token_for, csrf_token_valid, hash_password, hash_token, password_needs_rehash,
    verify_password,
)
from app.main import app
from app.tests.fake_auth_repo import FakeAuthRepo

EMAIL = "ramesh@example.com"
PASSWORD = "KisanPass123"
UA = "Mozilla/5.0 (Test Browser)"
ORIGIN = "http://localhost:3000"


# ─── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def repo(monkeypatch):
    fake = FakeAuthRepo()
    monkeypatch.setattr("app.services.auth_service.repo", fake)
    monkeypatch.setattr("app.api.auth.is_db_available", lambda: True)
    monkeypatch.setattr("app.api.deps.is_db_available", lambda: True)
    limiter.reset()
    yield fake
    limiter.reset()


@pytest.fixture
def outbox(monkeypatch):
    """Captures e-mails instead of sending them: list of (kind, to, token|None)."""
    sent = []

    def capture(kind, with_token):
        async def _send(to, token=None):
            sent.append((kind, to, token))
            return True
        async def _send_no_token(to):
            sent.append((kind, to, None))
            return True
        return _send if with_token else _send_no_token

    es = "app.services.auth_service.email_service"
    monkeypatch.setattr(f"{es}.send_password_reset_email", capture("reset", True))
    monkeypatch.setattr(f"{es}.send_account_exists_email", capture("exists", False))
    monkeypatch.setattr(f"{es}.send_password_changed_email", capture("changed", False))
    return sent


def browser(user_agent: str = UA) -> TestClient:
    """A fresh 'browser': own cookie jar, fixed User-Agent and the app's Origin."""
    return TestClient(app, headers={"User-Agent": user_agent, "Origin": ORIGIN})


def token_of(outbox, kind):
    return [t for k, _, t in outbox if k == kind][-1]


def register_account(c, outbox, email=EMAIL, password=PASSWORD):
    response = c.post("/auth/register", json={"email": email, "password": password})
    assert response.status_code == 202
    assert "sign in now" in response.json()["message"]
    assert "set-cookie" not in response.headers


def login(c, email=EMAIL, password=PASSWORD):
    return c.post("/auth/login", json={"email": email, "password": password})


def signed_in(c, outbox):
    register_account(c, outbox)
    r = login(c)
    assert r.status_code == 200, r.text
    return r.json()["csrf_token"]


# ─── password hashing (unit) ──────────────────────────────────────────────────

class TestPasswordHashing:
    def test_argon2id_hash_and_verify(self):
        h = hash_password(PASSWORD)
        assert h.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
        assert PASSWORD not in h
        assert verify_password(PASSWORD, h)
        assert not verify_password("WrongPass123", h)

    def test_unknown_account_does_not_crash_and_fails(self):
        assert verify_password(PASSWORD, None) is False
        assert verify_password(PASSWORD, "not-a-hash") is False

    def test_legacy_bcrypt_hash_still_verifies_and_needs_rehash(self):
        legacy = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
        assert verify_password(PASSWORD, legacy)
        assert password_needs_rehash(legacy)
        assert not password_needs_rehash(hash_password(PASSWORD))


# ─── registration ─────────────────────────────────────────────────────────────

class TestRegistration:
    def test_register_is_generic_and_immediately_sign_in_ready(self, repo, outbox):
        c = browser()
        r = c.post("/auth/register", json={"email": EMAIL, "password": PASSWORD, "full_name": "Ramesh"})
        assert r.status_code == 202
        assert "sign in now" in r.json()["message"]
        assert "set-cookie" not in r.headers
        assert not outbox
        f = repo.farmers[1]
        assert f.password_hash.startswith("$argon2id$") and not f.is_verified
        assert login(c).status_code == 200

    def test_duplicate_registration_gives_same_response_no_enumeration(self, repo, outbox):
        c = browser()
        first = c.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})
        second = c.post("/auth/register", json={"email": EMAIL.upper(), "password": "Other1234x"})
        assert first.status_code == second.status_code == 202
        assert first.json() == second.json()
        assert [k for k, _, _ in outbox] == ["exists"]
        assert len(repo.farmers) == 1

    def test_legacy_unverified_account_can_sign_in(self, repo, outbox):
        c = browser()
        register_account(c, outbox)
        repo.farmers[1] = repo.farmers[1].model_copy(update={"is_verified": False, "email_verified_at": None})
        r = login(c)
        assert r.status_code == 200
        assert not r.json()["user"]["is_verified"]
        assert not repo.farmers[1].is_verified

    def test_password_rules_validated(self, repo, outbox):
        c = browser()
        for bad in ("short1", "lettersonly", "12345678", "x1" * 70):
            r = c.post("/auth/register", json={"email": EMAIL, "password": bad})
            assert r.status_code == 422, bad


# ─── login, cookie, session ───────────────────────────────────────────────────

class TestLoginAndSession:
    def test_successful_login_sets_secure_session_cookie(self, repo, outbox):
        c = browser()
        register_account(c, outbox)
        r = login(c)
        assert r.status_code == 200
        body = r.json()
        assert body["user"]["email"] == EMAIL and body["csrf_token"]
        assert "token" not in str({k: v for k, v in body.items() if k != "csrf_token"}).lower()
        cookie = r.headers["set-cookie"]
        assert cookie.startswith(f"{settings.SESSION_COOKIE_NAME}=")
        assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/" in cookie
        assert f"Max-Age={settings.SESSION_ABSOLUTE_HOURS * 3600}" in cookie
        raw = c.cookies[settings.SESSION_COOKIE_NAME]
        assert repo.session_by_hash(hash_token(raw)) is not None          # only the hash is stored
        assert not any(s.session_hash == raw for s in repo.sessions.values())
        s = c.get("/auth/session")
        assert s.status_code == 200 and s.json()["user"]["email"] == EMAIL

    def test_cookie_is_secure_in_production(self, repo, outbox, monkeypatch):
        c = browser()
        register_account(c, outbox)
        monkeypatch.setattr(settings, "COOKIE_SECURE", True)
        assert "Secure" in login(c).headers["set-cookie"]

    def test_invalid_credentials_generic_for_wrong_password_and_unknown_email(self, repo, outbox):
        c = browser()
        register_account(c, outbox)
        wrong = login(c, password="WrongPass999")
        unknown = login(c, email="nobody@example.com")
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()
        assert settings.SESSION_COOKIE_NAME not in c.cookies

    def test_signed_out_session_endpoint_is_401(self, repo):
        assert browser().get("/auth/session").status_code == 401

    def test_lockout_after_repeated_failures(self, repo, outbox):
        c = browser()
        register_account(c, outbox)
        for _ in range(settings.LOGIN_MAX_FAILURES):
            assert login(c, password="WrongPass999").status_code == 401
        locked = login(c)                                        # correct password, but locked
        assert locked.status_code == 401
        assert locked.json()["error"]["code"] == "INVALID_CREDENTIALS"
        repo._update(1, locked_until=datetime.now(timezone.utc) - timedelta(seconds=1))
        assert login(c).status_code == 200                       # lock expired

    def test_successful_login_resets_failure_counter(self, repo, outbox):
        c = browser()
        register_account(c, outbox)
        for _ in range(settings.LOGIN_MAX_FAILURES - 1):
            login(c, password="WrongPass999")
        assert login(c).status_code == 200
        assert repo.farmers[1].failed_login_count == 0

    def test_legacy_bcrypt_user_upgraded_to_argon2_on_login(self, repo, outbox):
        legacy = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
        repo.farmers[1] = __import__("app.models.db.farmer_auth", fromlist=["FarmerRow"]).FarmerRow(
            id=1, farmer_id="uuid-legacy", email=EMAIL, password_hash=legacy, is_verified=True)
        assert login(browser()).status_code == 200
        assert repo.farmers[1].password_hash.startswith("$argon2id$")

    def test_session_expires_after_absolute_lifetime(self, repo, outbox):
        c = browser()
        signed_in(c, outbox)
        s = next(iter(repo.sessions.values()))
        repo.sessions[s.id] = s.model_copy(update={"expires_at": datetime.now(timezone.utc) - timedelta(seconds=1)})
        assert c.get("/auth/session").status_code == 401

    def test_session_expires_after_idle_timeout(self, repo, outbox):
        c = browser()
        signed_in(c, outbox)
        s = next(iter(repo.sessions.values()))
        idle = timedelta(minutes=settings.SESSION_IDLE_MINUTES + 1)
        repo.sessions[s.id] = s.model_copy(update={"last_seen_at": datetime.now(timezone.utc) - idle})
        assert c.get("/auth/session").status_code == 401
        assert repo.sessions[s.id].revoked_reason == "idle_timeout"


# ─── logout ───────────────────────────────────────────────────────────────────

class TestLogout:
    def test_logout_revokes_session_and_clears_cookie(self, repo, outbox):
        c = browser()
        csrf = signed_in(c, outbox)
        stolen = c.cookies[settings.SESSION_COOKIE_NAME]
        r = c.post("/auth/logout", headers={"X-CSRF-Token": csrf})
        assert r.status_code == 204
        assert f'{settings.SESSION_COOKIE_NAME}=""' in r.headers["set-cookie"]
        replay = browser()
        replay.cookies.set(settings.SESSION_COOKIE_NAME, stolen)
        assert replay.get("/auth/session").status_code == 401   # the old cookie is dead server-side

    def test_logout_requires_csrf_when_signed_in(self, repo, outbox):
        c = browser()
        signed_in(c, outbox)
        assert c.post("/auth/logout").status_code == 403
        assert c.get("/auth/session").status_code == 200

    def test_logout_without_session_is_harmless(self, repo):
        assert browser().post("/auth/logout").status_code == 204

    def test_logout_all_ends_every_device(self, repo, outbox):
        phone, laptop = browser("Phone UA"), browser("Laptop UA")
        register_account(phone, outbox)
        csrf = login(phone).json()["csrf_token"]
        assert login(laptop).status_code == 200
        assert phone.post("/auth/logout-all", headers={"X-CSRF-Token": csrf}).status_code == 200
        assert laptop.get("/auth/session").status_code == 401
        assert phone.get("/auth/session").status_code == 401


# ─── CSRF ─────────────────────────────────────────────────────────────────────

class TestCSRF:
    def test_csrf_token_bound_to_session(self):
        assert csrf_token_valid("session-a", csrf_token_for("session-a"))
        assert not csrf_token_valid("session-b", csrf_token_for("session-a"))
        assert not csrf_token_valid("session-a", None)

    def test_state_change_without_or_with_wrong_csrf_is_rejected(self, repo, outbox):
        c = browser()
        csrf = signed_in(c, outbox)
        body = {"current_password": PASSWORD, "new_password": "NewKisan456"}
        assert c.post("/auth/change-password", json=body).status_code == 403
        bad = c.post("/auth/change-password", json=body, headers={"X-CSRF-Token": "0" * 64})
        assert bad.status_code == 403 and bad.json()["detail"]["code"] == "CSRF_FAILED"
        ok = c.post("/auth/change-password", json=body, headers={"X-CSRF-Token": csrf})
        assert ok.status_code == 200

    def test_cross_site_origin_rejected(self, repo, outbox):
        c = browser()
        register_account(c, outbox)
        r = c.post("/auth/login", json={"email": EMAIL, "password": PASSWORD},
                   headers={"Origin": "https://evil.example"})
        assert r.status_code == 403 and r.json()["detail"]["code"] == "ORIGIN_NOT_ALLOWED"

    def test_chat_with_cookie_but_no_csrf_is_anonymous(self, repo, outbox):
        import asyncio
        from starlette.requests import Request
        from app.api.deps import get_optional_farmer_id
        c = browser()
        csrf = signed_in(c, outbox)
        raw = c.cookies[settings.SESSION_COOKIE_NAME]

        def req(headers):
            hdrs = [(b"cookie", f"{settings.SESSION_COOKIE_NAME}={raw}".encode()),
                    (b"user-agent", UA.encode())] + [(k.lower().encode(), v.encode()) for k, v in headers.items()]
            return Request({"type": "http", "method": "POST", "path": "/chat", "headers": hdrs,
                            "query_string": b""})

        assert asyncio.run(get_optional_farmer_id(req({}))) is None
        assert asyncio.run(get_optional_farmer_id(req({"X-CSRF-Token": csrf}))) == "uuid-1"


# ─── session hijacking attempts ───────────────────────────────────────────────

class TestSessionHijacking:
    def test_forged_or_tampered_cookie_rejected(self, repo, outbox):
        c = browser()
        signed_in(c, outbox)
        raw = c.cookies[settings.SESSION_COOKIE_NAME]
        for forged in (raw[:-2] + ("AA" if not raw.endswith("AA") else "BB"), "x" * 43, "", "a" * 500):
            attacker = browser()
            attacker.cookies.set(settings.SESSION_COOKIE_NAME, forged)
            assert attacker.get("/auth/session").status_code == 401

    def test_stolen_cookie_from_another_browser_is_rejected_and_revoked(self, repo, outbox):
        victim = browser(UA)
        signed_in(victim, outbox)
        attacker = browser("curl/8.0 attacker")
        attacker.cookies.set(settings.SESSION_COOKIE_NAME, victim.cookies[settings.SESSION_COOKIE_NAME])
        assert attacker.get("/auth/session").status_code == 401
        assert victim.get("/auth/session").status_code == 401        # compromised session revoked
        assert next(iter(repo.sessions.values())).revoked_reason == "user_agent_mismatch"

    def test_session_fixation_login_issues_a_new_session(self, repo, outbox):
        c = browser()
        register_account(c, outbox)
        planted = login(c).cookies[settings.SESSION_COOKIE_NAME]     # attacker-known session
        c.cookies.set(settings.SESSION_COOKIE_NAME, planted)
        fresh = login(c).cookies[settings.SESSION_COOKIE_NAME]
        assert fresh != planted
        old = browser()
        old.cookies.set(settings.SESSION_COOKIE_NAME, planted)
        assert old.get("/auth/session").status_code == 401           # pre-login session ended

    def test_session_cookie_never_in_response_body(self, repo, outbox):
        c = browser()
        register_account(c, outbox)
        r = login(c)
        assert r.cookies[settings.SESSION_COOKIE_NAME] not in r.text
        assert c.cookies[settings.SESSION_COOKIE_NAME] not in c.get("/auth/session").text


# ─── forgot / reset / change password ─────────────────────────────────────────

class TestPasswordRecovery:
    def test_forgot_password_generic_and_never_returns_token(self, repo, outbox):
        c = browser()
        register_account(c, outbox)
        known = c.post("/auth/forgot-password", json={"email": EMAIL})
        unknown = c.post("/auth/forgot-password", json={"email": "nobody@example.com"})
        assert known.status_code == unknown.status_code == 202
        assert known.json() == unknown.json()
        token = token_of(outbox, "reset")
        assert token not in known.text and "_dev_token" not in known.text
        assert len([1 for k, _, _ in outbox if k == "reset"]) == 1    # nothing sent for unknown

    def test_reset_token_is_short_lived(self, repo, outbox):
        c = browser()
        register_account(c, outbox)
        c.post("/auth/forgot-password", json={"email": EMAIL})
        lifetime = repo.tokens[-1]["expires_at"] - datetime.now(timezone.utc)
        assert timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES - 1) < lifetime <= \
               timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES)
        assert settings.PASSWORD_RESET_EXPIRE_MINUTES <= 60

    def test_reset_password_flow_revokes_sessions_and_is_single_use(self, repo, outbox):
        c = browser()
        signed_in(c, outbox)
        other_device = browser("Other device")
        assert login(other_device).status_code == 200
        c.post("/auth/forgot-password", json={"email": EMAIL})
        token = token_of(outbox, "reset")
        r = c.post("/auth/reset-password", json={"token": token, "new_password": "BrandNew789"})
        assert r.status_code == 200
        assert c.get("/auth/session").status_code == 401
        assert other_device.get("/auth/session").status_code == 401
        assert login(browser(), password=PASSWORD).status_code == 401
        assert login(browser(), password="BrandNew789").status_code == 200
        again = c.post("/auth/reset-password", json={"token": token, "new_password": "Another789x"})
        assert again.status_code == 400 and again.json()["error"]["code"] == "INVALID_TOKEN"
        assert ("changed", EMAIL, None) in outbox

    def test_expired_reset_token_rejected(self, repo, outbox):
        c = browser()
        register_account(c, outbox)
        c.post("/auth/forgot-password", json={"email": EMAIL})
        repo.tokens[-1]["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
        r = c.post("/auth/reset-password", json={"token": token_of(outbox, "reset"),
                                                  "new_password": "BrandNew789"})
        assert r.status_code == 400
        assert login(c).status_code == 200                            # password unchanged

    def test_new_reset_request_invalidates_previous_link(self, repo, outbox):
        c = browser()
        register_account(c, outbox)
        c.post("/auth/forgot-password", json={"email": EMAIL})
        first = token_of(outbox, "reset")
        c.post("/auth/forgot-password", json={"email": EMAIL})
        assert c.post("/auth/reset-password", json={"token": first, "new_password": "BrandNew789"}).status_code == 400
        assert c.post("/auth/reset-password", json={"token": token_of(outbox, "reset"),
                                                     "new_password": "BrandNew789"}).status_code == 200

    def test_reset_unlocks_a_locked_account(self, repo, outbox):
        c = browser()
        register_account(c, outbox)
        for _ in range(settings.LOGIN_MAX_FAILURES):
            login(c, password="WrongPass999")
        c.post("/auth/forgot-password", json={"email": EMAIL})
        c.post("/auth/reset-password", json={"token": token_of(outbox, "reset"), "new_password": "BrandNew789"})
        assert login(c, password="BrandNew789").status_code == 200

    def test_change_password_rotates_session_and_signs_out_others(self, repo, outbox):
        c = browser()
        csrf = signed_in(c, outbox)
        old_cookie = c.cookies[settings.SESSION_COOKIE_NAME]
        other = browser("Other device")
        assert login(other).status_code == 200
        wrong = c.post("/auth/change-password", headers={"X-CSRF-Token": csrf},
                       json={"current_password": "Nope12345", "new_password": "NewKisan456"})
        assert wrong.status_code == 400
        r = c.post("/auth/change-password", headers={"X-CSRF-Token": csrf},
                   json={"current_password": PASSWORD, "new_password": "NewKisan456"})
        assert r.status_code == 200
        new_cookie = c.cookies[settings.SESSION_COOKIE_NAME]
        assert new_cookie != old_cookie
        assert c.get("/auth/session").status_code == 200              # this device stays signed in
        assert other.get("/auth/session").status_code == 401          # others signed out
        stale = browser()
        stale.cookies.set(settings.SESSION_COOKIE_NAME, old_cookie)
        assert stale.get("/auth/session").status_code == 401
        assert login(browser(), password="NewKisan456").status_code == 200


# ─── rate limiting ────────────────────────────────────────────────────────────

class TestRateLimiting:
    def test_login_rate_limited_per_account(self, repo, outbox, monkeypatch):
        monkeypatch.setitem(__import__("app.core.rate_limit", fromlist=["LIMITS"]).LIMITS, "login_email", (3, 900))
        c = browser()
        register_account(c, outbox)
        for _ in range(3):
            login(c, password="WrongPass999")
        r = login(c)
        assert r.status_code == 429
        assert int(r.headers["Retry-After"]) > 0

    def test_forgot_password_rate_limited_per_email(self, repo, outbox):
        c = browser()
        codes = [c.post("/auth/forgot-password", json={"email": EMAIL}).status_code for _ in range(4)]
        assert codes == [202, 202, 202, 429]

    def test_register_rate_limited_per_ip(self, repo, outbox):
        c = browser()
        codes = [c.post("/auth/register", json={"email": f"u{i}@example.com", "password": PASSWORD}).status_code
                 for i in range(6)]
        assert codes[:5] == [202] * 5 and codes[5] == 429


# ─── e-mail service (dev mode) ────────────────────────────────────────────────

def test_dev_email_logged_with_link_but_not_in_production(monkeypatch, caplog):
    import asyncio
    import logging
    from app.services import email_service
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    with caplog.at_level(logging.WARNING):
        asyncio.run(email_service.send_password_reset_email("ramesh@example.com", "TOKEN123abc"))
    assert "reset-password?token=TOKEN123abc" in caplog.text
    assert "ramesh@example.com" not in caplog.text                    # address masked
    caplog.clear()
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    with caplog.at_level(logging.WARNING):
        sent = asyncio.run(email_service.send_password_reset_email("ramesh@example.com", "TOKEN123abc"))
    assert sent is False and "TOKEN123abc" not in caplog.text
    assert re.search(r"r\*\*\*@example\.com", caplog.text)
