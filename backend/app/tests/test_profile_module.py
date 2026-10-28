"""
Farmer profile module: save/load, validation, unknown values, corrections,
conflicting edits (version + chat), missing fields and cross-user access —
through the real HTTP API with real cookie sessions (in-memory account and
profile stores). The SQL is covered by test_profile_repository_pg.py.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.rate_limit import limiter
from app.database.repositories.profile_repository import PROFILE_COLUMNS, VersionConflict
from app.main import app
from app.models.db.farmer_auth import FarmerProfileRow
from app.services import chat_profile_service as cps
from app.services.profile_service import income_to_range, land_to_acres, missing_fields
from app.tests.fake_auth_repo import FakeAuthRepo

UA = "Mozilla/5.0 (Profile Test)"
ORIGIN = "http://localhost:3000"


class FakeProfileRepo:
    """In-memory profile_repository with the same version / conflict semantics."""

    VersionConflict = VersionConflict

    def __init__(self, auth: FakeAuthRepo):
        self.auth = auth
        self.rows: dict[int, FarmerProfileRow] = {}

    async def get_farmer_by_farmer_id(self, farmer_id):
        return next((f for f in self.auth.farmers.values() if f.farmer_id == farmer_id), None)

    async def get_profile(self, pk):
        return self.rows.get(pk)

    async def save_profile(self, pk, changes, expected_version):
        assert set(changes) <= set(PROFILE_COLUMNS)
        now = datetime.now(timezone.utc)
        row = self.rows.get(pk)
        if row is None:
            if expected_version not in (None, 0):
                raise VersionConflict()
            row = FarmerProfileRow(id=pk, farmer_id=pk, version=1, created_at=now, updated_at=now, **changes)
        else:
            if expected_version is not None and expected_version != row.version:
                raise VersionConflict()
            row = row.model_copy(update={**changes, "version": row.version + 1, "updated_at": now})
        self.rows[pk] = row
        return row


@pytest.fixture
def stores(monkeypatch):
    auth = FakeAuthRepo()
    prof = FakeProfileRepo(auth)
    monkeypatch.setattr("app.services.auth_service.repo", auth)
    monkeypatch.setattr("app.services.profile_service.profile_repo", prof)
    monkeypatch.setattr("app.api.auth.is_db_available", lambda: True)
    monkeypatch.setattr("app.api.deps.is_db_available", lambda: True)
    for name in ("send_password_reset_email",
                 "send_account_exists_email", "send_password_changed_email"):
        async def _noop(*a, **k):
            return True
        monkeypatch.setattr(f"app.services.auth_service.email_service.{name}", _noop)
    limiter.reset()
    yield auth, prof
    limiter.reset()


class Farmer:
    """A signed-in farmer: own browser (cookie jar) + CSRF token."""

    def __init__(self, auth: FakeAuthRepo, email: str):
        self.c = TestClient(app, headers={"User-Agent": UA, "Origin": ORIGIN})
        assert self.c.post("/auth/register", json={"email": email, "password": "KisanPass123"}).status_code == 202
        auth._update(next(f.id for f in auth.farmers.values() if f.email == email), is_verified=True)
        r = self.c.post("/auth/login", json={"email": email, "password": "KisanPass123"})
        assert r.status_code == 200, r.text
        self.csrf = r.json()["csrf_token"]
        self.farmer_id = r.json()["user"]["farmer_id"]

    def put(self, body, csrf=True):
        return self.c.put("/farmers/me/profile", json=body,
                          headers={"X-CSRF-Token": self.csrf} if csrf else {})

    def get(self):
        return self.c.get("/farmers/me/profile")


FULL = {"state": "KA", "district": "Mandya", "land_size": 2, "land_unit": "hectare",
        "primary_crop": "Finger Millet", "occupation": "Farmer", "age": 42, "gender": "F",
        "category": "scheduled caste", "income_range": "1_to_2.5_lakh", "residence": "rural",
        "consent_given": True}


# ─── save / load ──────────────────────────────────────────────────────────────

class TestSaveLoad:
    def test_no_profile_yet_is_404(self, stores):
        assert Farmer(stores[0], "a@example.com").get().status_code == 404

    def test_save_then_load_canonicalised(self, stores):
        f = Farmer(stores[0], "a@example.com")
        r = f.put(FULL)
        assert r.status_code == 200, r.text
        p = f.get().json()
        assert p["state"] == "Karnataka" and p["primary_crop"] == "ragi"
        assert p["land_size"] == 2 and p["land_unit"] == "hectare"
        assert p["land_size_acres"] == pytest.approx(4.9421)          # what the engine uses
        assert (p["gender"], p["category"], p["occupation"]) == ("female", "SC", "farmer")
        assert p["income_range"] == "1_to_2.5_lakh" and p["residence"] == "rural"
        assert p["version"] == 1 and p["consent_given"] is True
        assert "has_aadhaar" not in p and "annual_income" not in p    # not collected

    @pytest.mark.parametrize("value,unit,acres", [(40, "guntha", 1.0), (50, "cent", 0.5),
                                                  (3.5, "acre", 3.5), (1, "hectare", 2.4711)])
    def test_land_units_converted_to_acres(self, value, unit, acres):
        assert land_to_acres(value, unit) == pytest.approx(acres, abs=1e-4)

    def test_consent_required_before_first_save(self, stores):
        f = Farmer(stores[0], "a@example.com")
        r = f.put({"state": "Karnataka"})
        assert r.status_code == 403 and r.json()["detail"]["code"] == "CONSENT_REQUIRED"
        assert stores[1].rows == {}


# ─── unknown values, corrections, partial updates ─────────────────────────────

class TestUnknownAndCorrections:
    def test_optional_fields_stay_unknown_not_false(self, stores):
        f = Farmer(stores[0], "a@example.com")
        p = f.put({"state": "Karnataka", "consent_given": True}).json()
        for field in ("age", "gender", "category", "income_range", "residence", "occupation",
                      "land_size", "land_size_acres", "district"):
            assert p[field] is None, field                             # UNKNOWN, never False/0

    def test_zero_land_is_a_value_not_unknown(self, stores):
        f = Farmer(stores[0], "a@example.com")
        p = f.put({"land_size": 0, "land_unit": "acre", "consent_given": True}).json()
        assert p["land_size"] == 0 and p["land_size_acres"] == 0

    def test_omitted_fields_unchanged(self, stores):
        f = Farmer(stores[0], "a@example.com")
        f.put(FULL)
        p = f.put({"district": "Hassan"}).json()
        assert p["district"] == "Hassan" and p["state"] == "Karnataka" and p["age"] == 42

    def test_correction_and_clearing_back_to_unknown(self, stores):
        f = Farmer(stores[0], "a@example.com")
        f.put(FULL)
        p = f.put({"age": None, "land_size": None, "gender": None, "primary_crop": "maize"}).json()
        assert p["age"] is None and p["gender"] is None
        assert p["land_size"] is None and p["land_unit"] is None and p["land_size_acres"] is None
        assert p["primary_crop"] == "maize"
        assert p["version"] == 2

    def test_missing_fields_reported(self, stores):
        f = Farmer(stores[0], "a@example.com")
        f.put({"state": "Karnataka", "consent_given": True})
        row = next(iter(stores[1].rows.values()))
        assert missing_fields(row) == ["primary_crop", "land_size_acres"]
        assert missing_fields(None) == ["state", "primary_crop", "land_size_acres"]
        assert f.get().json()["profile_completeness"] == 10.0            # 1 of 10 fields known


# ─── validation ───────────────────────────────────────────────────────────────

class TestValidation:
    @pytest.mark.parametrize("body", [
        {"state": "Xyzland"},
        {"land_size": -1, "land_unit": "acre"},
        {"land_size": 2},                                   # unit missing
        {"land_unit": "acre"},                              # value missing
        {"land_size": 2, "land_unit": "bigha"},             # size differs by state: not offered
        {"age": 0}, {"age": 150},
        {"gender": "unknown"}, {"category": "XYZ"},
        {"income_range": "lots"}, {"residence": "moon"},
        {"district": "   "}, {"district": "<script>alert(1)</script>"},
        {"other_crops": ["rice"] * 11},
        {"aadhaar_number": "1234 5678 9012"},               # never collected
        {"has_aadhaar": True}, {"annual_income": 150000},   # not collected (no rule uses them)
        {"farmer_id": "uuid-2"},                            # cannot name another account
    ])
    def test_invalid_input_rejected(self, stores, body):
        f = Farmer(stores[0], "a@example.com")
        r = f.put({**body, "consent_given": True})
        assert r.status_code == 422, (body, r.text)
        assert stores[1].rows == {}


# ─── conflicting corrections ──────────────────────────────────────────────────

class TestConflicts:
    def test_stale_edit_rejected_with_409(self, stores):
        f = Farmer(stores[0], "a@example.com")
        v1 = f.put(FULL).json()["version"]
        assert f.put({"district": "Hassan", "expected_version": v1}).status_code == 200   # device A
        stale = f.put({"district": "Tumkur", "expected_version": v1})                    # device B, old copy
        assert stale.status_code == 409 and stale.json()["detail"]["code"] == "CONFLICT"
        p = f.get().json()
        assert p["district"] == "Hassan" and p["version"] == v1 + 1
        assert f.put({"district": "Tumkur", "expected_version": p["version"]}).status_code == 200

    def test_saved_profile_wins_over_stale_chat_value_when_synced(self):
        chat_memory = {"district": "Mandya", "state": "Karnataka", "age": None}
        saved = {"district": "Hassan", "state": "Karnataka", "primary_crop": "ragi"}
        merged = cps.merge_chat_profiles(chat_memory, saved, saved_is_authoritative=True)
        assert merged["district"] == "Hassan" and merged["primary_crop"] == "ragi"
        not_synced = cps.merge_chat_profiles(chat_memory, saved, saved_is_authoritative=False)
        assert not_synced["district"] == "Mandya"                       # only fills gaps

    def test_unknown_saved_value_never_erases_chat_value(self):
        assert cps.merge_chat_profiles({"age": 40}, {"age": None}, True)["age"] == 40

    @pytest.mark.asyncio
    async def test_chat_saves_only_fields_changed_this_turn(self, monkeypatch):
        captured = []

        async def fake_update(farmer_id, req):
            captured.append(req.model_dump(exclude_unset=True))
            return object()

        monkeypatch.setattr(cps, "update_profile", fake_update)
        before = {"state": "Karnataka", "district": "Hassan", "land_size_acres": 2.0}
        after = {**before, "age": 35, "has_aadhaar": True, "annual_income": 180000}
        assert await cps.save_chat_profile("uuid-1", after, consent_to_save=False,
                                           existing_consent=True, previous=before)
        assert captured == [{"age": 35, "income_range": "1_to_2.5_lakh", "consent_given": True}]
        # nothing new this turn -> no write (no version bump, no overwrite)
        captured.clear()
        assert not await cps.save_chat_profile("uuid-1", before, consent_to_save=False,
                                               existing_consent=True, previous=before)
        assert captured == []

    @pytest.mark.asyncio
    async def test_first_chat_consent_saves_everything_known_but_never_aadhaar(self, monkeypatch):
        captured = []

        async def fake_update(farmer_id, req):
            captured.append(req.model_dump(exclude_unset=True))
            return object()

        monkeypatch.setattr(cps, "update_profile", fake_update)
        profile = {"state": "Karnataka", "land_size_acres": 2.0, "primary_crop": "ragi",
                   "has_aadhaar": True, "district": "<bad>"}
        assert await cps.save_chat_profile("uuid-1", profile, consent_to_save=True,
                                           existing_consent=False, previous=profile)
        saved = captured[0]
        assert saved["land_size"] == 2.0 and saved["land_unit"] == "acre"
        assert "has_aadhaar" not in saved and "district" not in saved   # invalid value skipped
        assert saved["consent_given"] is True

    def test_income_ranges(self):
        assert [income_to_range(x) for x in (0, 99_999, 100_000, 250_000, 600_000, 2_000_000)] == [
            "below_1_lakh", "below_1_lakh", "1_to_2.5_lakh", "2.5_to_5_lakh", "5_to_10_lakh", "above_10_lakh"]


# ─── binding to the authenticated user / cross-user access ────────────────────

class TestCrossUserAccess:
    def test_each_farmer_only_sees_and_changes_their_own_profile(self, stores):
        a = Farmer(stores[0], "a@example.com")
        b = Farmer(stores[0], "b@example.com")
        a.put(FULL)
        assert b.get().status_code == 404                                # B has no profile; A's is invisible
        b.put({"state": "Punjab", "consent_given": True})
        assert a.get().json()["state"] == "Karnataka"                    # A untouched
        assert b.get().json()["state"] == "Punjab"
        pks = {f.id for f in stores[0].farmers.values()}
        assert set(stores[1].rows) == pks and len(pks) == 2              # one row per account

    def test_body_cannot_target_another_account(self, stores):
        a = Farmer(stores[0], "a@example.com")
        b = Farmer(stores[0], "b@example.com")
        a.put(FULL)
        r = b.put({"farmer_id": a.farmer_id, "state": "Punjab", "consent_given": True})
        assert r.status_code == 422
        assert a.get().json()["state"] == "Karnataka"

    def test_no_route_takes_a_farmer_id(self):
        paths = [r.path for r in app.routes if getattr(r, "path", "").startswith("/farmers")]
        assert paths and all(p.startswith("/farmers/me/") for p in paths)
        assert not any("{farmer" in p for p in paths)

    def test_signed_out_and_csrf_less_requests_rejected(self, stores):
        a = Farmer(stores[0], "a@example.com")
        anon = TestClient(app, headers={"User-Agent": UA})
        assert anon.get("/farmers/me/profile").status_code == 401
        assert anon.put("/farmers/me/profile", json={"state": "Punjab"}).status_code == 401
        assert a.put({"state": "Punjab", "consent_given": True}, csrf=False).status_code == 403
        assert stores[1].rows == {}

    def test_stolen_cookie_cannot_read_profile(self, stores):
        a = Farmer(stores[0], "a@example.com")
        a.put(FULL)
        thief = TestClient(app, headers={"User-Agent": "curl/8"})
        thief.cookies.set("ss_session", a.c.cookies["ss_session"])
        assert thief.get("/farmers/me/profile").status_code == 401


# ─── the eligibility engine gets the saved profile ────────────────────────────

@pytest.mark.asyncio
async def test_saved_profile_feeds_engine_fields(stores):
    a = Farmer(stores[0], "a@example.com")
    a.put(FULL)
    values, consent = await cps.load_saved_chat_profile(a.farmer_id)
    assert consent is True
    assert values["land_size_acres"] == pytest.approx(4.9421)
    assert values["residence"] == "rural" and values["occupation"] == "farmer"
    assert "income_range" not in values and "has_aadhaar" not in values
