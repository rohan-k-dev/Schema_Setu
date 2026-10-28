"""
Personalized dashboard: eligibility from the saved profile (deterministic engine),
recalculation and staleness, missing / conflicting details, pagination, and the
search-history retention policy with per-item delete / clear — through the real
HTTP API with real cookie sessions for two farmers. In-memory stores stand in for
PostgreSQL; the history SQL is covered by test_search_history_pg.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core.rate_limit import limiter
from app.database.repositories.search_history_repository import MAX_ENTRIES, RETENTION_DAYS
from app.models.db import EligibilityRuleRow, SchemeRow
from app.models.db.farmer_auth import SavedSchemeRow, SearchHistoryRow
from app.services import profile_service
from app.tests.fake_auth_repo import FakeAuthRepo
from app.tests.test_profile_module import FakeProfileRepo, Farmer

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


# ─── in-memory stand-ins ──────────────────────────────────────────────────────

def _scheme(pk, sid, name, **kw):
    return SchemeRow(id=pk, scheme_id=sid, name=name, description=name,
                     official_url=f"https://example.gov.in/{sid}", updated_at=T0, **kw)


def _rule(pk, scheme_pk, field, op, value, order=0):
    return EligibilityRuleRow(id=pk, scheme_id=scheme_pk, field_name=field, operator=op,
                              value_json=value, rule_order=order)


class FakeCorpus:
    """Active schemes + rules, shaped like SchemeRepository / RuleRepository."""

    def __init__(self):
        self.down = False
        self.schemes = [
            _scheme(1, "AGE_SCHEME", "Pension for 18-40"),
            _scheme(2, "LAND_SCHEME", "Landholder Support"),
            _scheme(3, "KA_SCHEME", "Karnataka Farmers"),
            _scheme(4, "NO_RULES", "Scheme Without Rules"),
            _scheme(5, "FARMER_SCHEME", "Farmer Machinery"),
        ]
        self.rules = {
            "AGE_SCHEME": [_rule(1, 1, "age", "BETWEEN", [18, 40])],
            "LAND_SCHEME": [_rule(2, 2, "has_land", "BOOLEAN", True)],
            "KA_SCHEME": [_rule(3, 3, "state", "IN", ["Karnataka"])],
            "NO_RULES": [],
            "FARMER_SCHEME": [_rule(4, 5, "occupation", "EQ", "farmer")],
        }

    async def list_active(self):
        if self.down:
            raise RuntimeError("db down")
        return [s for s in self.schemes if s.status == "ACTIVE"]

    async def list_for_scheme_ids(self, ids):
        return {i: list(self.rules.get(i, [])) for i in ids}


class FakeHistoryRepo:
    """search_history_repository with the same retention and ownership rules."""

    def __init__(self):
        self.rows: list[SearchHistoryRow] = []
        self.next_id = 1
        self.now = datetime.now(timezone.utc)

    def _prune(self, pk):
        cutoff = self.now - timedelta(days=RETENTION_DAYS)
        self.rows = [r for r in self.rows if not (r.farmer_id == pk and r.searched_at < cutoff)]

    def _mine(self, pk):
        return sorted((r for r in self.rows if r.farmer_id == pk),
                      key=lambda r: (r.searched_at, r.id), reverse=True)

    async def add(self, pk, query, results_count, language, at=None):
        self.now = max(self.now, at or self.now) + timedelta(seconds=1)
        self.rows.append(SearchHistoryRow(id=self.next_id, farmer_id=pk, query=query,
                                          results_count=results_count, language=language,
                                          searched_at=at or self.now))
        self.next_id += 1
        self._prune(pk)
        keep = {r.id for r in self._mine(pk)[:MAX_ENTRIES]}
        self.rows = [r for r in self.rows if r.farmer_id != pk or r.id in keep]

    async def list_page(self, pk, limit, offset):
        self._prune(pk)
        mine = self._mine(pk)
        return mine[offset:offset + limit], len(mine)

    async def delete_one(self, pk, entry_id):
        before = len(self.rows)
        self.rows = [r for r in self.rows if not (r.id == entry_id and r.farmer_id == pk)]
        return len(self.rows) < before

    async def clear(self, pk):
        n = sum(1 for r in self.rows if r.farmer_id == pk)
        self.rows = [r for r in self.rows if r.farmer_id != pk]
        return n


@pytest.fixture
def env(monkeypatch):
    auth = FakeAuthRepo()
    prof = FakeProfileRepo(auth)
    corpus = FakeCorpus()
    history = FakeHistoryRepo()
    saved: dict[int, list[SavedSchemeRow]] = {}

    async def pk_of(farmer_id):
        return next((f.id for f in auth.farmers.values() if f.farmer_id == farmer_id), None)

    async def saved_of(pk):
        return saved.get(pk, [])

    monkeypatch.setattr("app.services.auth_service.repo", auth)
    monkeypatch.setattr("app.services.profile_service.profile_repo", prof)
    monkeypatch.setattr("app.services.profile_service.history_repo", history)
    monkeypatch.setattr("app.services.profile_service.get_farmer_pk", pk_of)
    monkeypatch.setattr("app.services.profile_service.get_saved_schemes", saved_of)
    monkeypatch.setattr("app.services.dashboard_service.SchemeRepository", corpus)
    monkeypatch.setattr("app.services.dashboard_service.RuleRepository", corpus)
    monkeypatch.setattr("app.api.auth.is_db_available", lambda: True)
    monkeypatch.setattr("app.api.deps.is_db_available", lambda: True)
    for name in ("send_verification_email", "send_password_reset_email",
                 "send_account_exists_email", "send_password_changed_email"):
        async def _noop(*a, **k):
            return True
        monkeypatch.setattr(f"app.services.auth_service.email_service.{name}", _noop)
    limiter.reset()
    yield SimpleNamespace(auth=auth, prof=prof, corpus=corpus, history=history, saved=saved,
                          farmer=lambda email: Farmer(auth, email))
    limiter.reset()


def pk(env, f: Farmer) -> int:
    return next(x.id for x in env.auth.farmers.values() if x.farmer_id == f.farmer_id)


def elig(f: Farmer, **params):
    r = f.c.get("/farmers/me/eligibility", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def status_of(body, scheme_id):
    return next(i["status"] for i in body["items"] if i["scheme_id"] == scheme_id)


BASE = {"state": "Karnataka", "occupation": "farmer", "consent_given": True}


# ─── eligibility from the saved profile ──────────────────────────────────────

class TestEligibility:
    def test_no_profile_gives_needs_more_information_not_ineligible(self, env):
        body = elig(env.farmer("a@example.com"), page_size=50)
        assert body["has_profile"] is False and body["basis"]["profile_version"] is None
        assert body["counts"] == {"ELIGIBLE": 0, "NOT_ELIGIBLE": 0,
                                  "NEEDS_MORE_INFORMATION": 4, "UNVERIFIABLE": 1}
        assert status_of(body, "NO_RULES") == "UNVERIFIABLE"
        note = next(i for i in body["items"] if i["scheme_id"] == "NO_RULES")["status_note"]
        assert "no checkable eligibility rules" in note

    def test_statuses_come_from_the_deterministic_engine(self, env):
        f = env.farmer("a@example.com")
        f.put({**BASE, "age": 55, "land_size": 0, "land_unit": "acre"})
        body = elig(f, page_size=50)
        assert status_of(body, "KA_SCHEME") == "ELIGIBLE"
        assert status_of(body, "FARMER_SCHEME") == "ELIGIBLE"
        assert status_of(body, "AGE_SCHEME") == "NOT_ELIGIBLE"          # 55 is outside 18-40
        assert status_of(body, "LAND_SCHEME") == "NOT_ELIGIBLE"         # 0 acres = landless
        assert sum(body["counts"].values()) == 5 == body["total"]
        failed = next(i for i in body["items"] if i["scheme_id"] == "AGE_SCHEME")["failed_criteria"]
        assert failed[0]["field"] == "age" and failed[0]["user_value"] == 55
        # ranked: eligible first, unverifiable last
        assert [i["status"] for i in body["items"]][:2] == ["ELIGIBLE", "ELIGIBLE"]
        assert body["items"][-1]["status"] == "UNVERIFIABLE"

    def test_llm_is_never_called(self, env, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("LLM must not decide eligibility")
        monkeypatch.setattr("app.services.llm_service.get_llm", boom, raising=False)
        f = env.farmer("a@example.com")
        f.put(BASE)
        assert elig(f)["counts"]["ELIGIBLE"] == 2

    def test_missing_details_listed_with_affected_schemes(self, env):
        f = env.farmer("a@example.com")
        f.put(BASE)
        missing = {m["field"]: m for m in elig(f)["missing_details"]}
        assert set(missing) == {"age", "land_size"}                     # has_land → edit land size
        assert missing["age"]["schemes"] == ["Pension for 18-40"]
        assert missing["land_size"]["label"] == "Land size"

    def test_conflicting_details_are_reported(self, env):
        f = env.farmer("a@example.com")
        f.put({**BASE, "category": "EWS", "income_range": "above_10_lakh"})
        conflicts = elig(f)["conflicts"]
        assert len(conflicts) == 1 and conflicts[0]["fields"] == ["category", "income_range"]
        f.put({"income_range": "1_to_2.5_lakh", "consent_given": True})
        assert elig(f)["conflicts"] == []

    def test_saved_scheme_status_change_is_flagged(self, env):
        f = env.farmer("a@example.com")
        f.put({**BASE, "age": 30})
        env.saved[pk(env, f)] = [
            SavedSchemeRow(id=1, farmer_id=pk(env, f), scheme_id="AGE_SCHEME",
                           scheme_name="Pension for 18-40", eligibility_status="NEEDS_MORE_INFORMATION"),
            SavedSchemeRow(id=2, farmer_id=pk(env, f), scheme_id="KA_SCHEME",
                           scheme_name="Karnataka Farmers", eligibility_status="ELIGIBLE"),
        ]
        body = elig(f, page_size=50)
        assert body["saved_status_changes"] == [{
            "scheme_id": "AGE_SCHEME", "scheme_name": "Pension for 18-40",
            "saved_status": "NEEDS_MORE_INFORMATION", "current_status": "ELIGIBLE"}]
        ka = next(i for i in body["items"] if i["scheme_id"] == "KA_SCHEME")
        assert ka["saved"] and not ka["status_changed_since_saved"]


# ─── recalculation and staleness ─────────────────────────────────────────────

class TestRecalculation:
    def test_profile_update_then_recalculate_changes_status(self, env):
        f = env.farmer("a@example.com")
        f.put(BASE)
        before = elig(f, page_size=50)
        assert status_of(before, "AGE_SCHEME") == "NEEDS_MORE_INFORMATION"

        r = f.put({"age": 30, "consent_given": True,
                   "expected_version": before["basis"]["profile_version"]})
        assert r.status_code == 200
        # the shown result is now stale: the current basis differs
        basis = f.c.get("/farmers/me/eligibility/basis").json()
        assert basis["profile_version"] == before["basis"]["profile_version"] + 1
        assert basis["data_fingerprint"] == before["basis"]["data_fingerprint"]

        after = elig(f, page_size=50)
        assert status_of(after, "AGE_SCHEME") == "ELIGIBLE"
        assert after["basis"] == basis
        assert "age" not in {m["field"] for m in after["missing_details"]}

    def test_clearing_a_detail_goes_back_to_needs_more_information(self, env):
        f = env.farmer("a@example.com")
        f.put({**BASE, "age": 30})
        assert status_of(elig(f, page_size=50), "AGE_SCHEME") == "ELIGIBLE"
        f.put({"age": None, "consent_given": True})
        assert status_of(elig(f, page_size=50), "AGE_SCHEME") == "NEEDS_MORE_INFORMATION"

    def test_rule_change_changes_fingerprint_and_result(self, env):
        f = env.farmer("a@example.com")
        f.put({**BASE, "age": 45})
        before = elig(f, page_size=50)
        assert status_of(before, "AGE_SCHEME") == "NOT_ELIGIBLE"

        env.corpus.rules["AGE_SCHEME"] = [_rule(1, 1, "age", "BETWEEN", [18, 50])]
        basis = f.c.get("/farmers/me/eligibility/basis").json()
        assert basis["data_fingerprint"] != before["basis"]["data_fingerprint"]
        assert basis["profile_version"] == before["basis"]["profile_version"]
        assert status_of(elig(f, page_size=50), "AGE_SCHEME") == "ELIGIBLE"

    def test_scheme_record_change_changes_fingerprint(self, env):
        f = env.farmer("a@example.com")
        fp = f.c.get("/farmers/me/eligibility/basis").json()["data_fingerprint"]
        env.corpus.schemes[2] = env.corpus.schemes[2].model_copy(update={"status": "INACTIVE"})
        basis = f.c.get("/farmers/me/eligibility/basis").json()
        assert basis["data_fingerprint"] != fp and basis["scheme_count"] == 4
        assert "KA_SCHEME" not in {i["scheme_id"] for i in elig(f, page_size=50)["items"]}

    def test_same_inputs_give_same_basis_and_order(self, env):
        f = env.farmer("a@example.com")
        f.put(BASE)
        a, b = elig(f, page_size=50), elig(f, page_size=50)
        assert a["basis"] == b["basis"] and a["items"] == b["items"]


# ─── pagination, filters, validation ─────────────────────────────────────────

class TestPagination:
    def test_pages_and_status_filter(self, env):
        f = env.farmer("a@example.com")
        f.put(BASE)
        p1, p3 = elig(f, page_size=2), elig(f, page_size=2, page=3)
        assert (len(p1["items"]), p1["total"], len(p3["items"])) == (2, 5, 1)
        assert p1["items"][0]["rank"] == 1 and p3["items"][0]["rank"] == 5
        assert elig(f, page_size=2, page=9)["items"] == []
        only = elig(f, status="ELIGIBLE")
        assert only["total"] == 2 and {i["status"] for i in only["items"]} == {"ELIGIBLE"}
        assert only["counts"]["NEEDS_MORE_INFORMATION"] == 2           # counts are unfiltered

    @pytest.mark.parametrize("params", [{"status": "MAYBE"}, {"page": 0}, {"page_size": 51},
                                        {"page_size": 0}, {"page": "x"}])
    def test_invalid_parameters_are_422(self, env, params):
        assert env.farmer("a@example.com").c.get("/farmers/me/eligibility", params=params).status_code == 422

    def test_scheme_data_unavailable_is_503(self, env):
        f = env.farmer("a@example.com")
        env.corpus.down = True
        for path in ("/farmers/me/eligibility", "/farmers/me/eligibility/basis"):
            r = f.c.get(path)
            assert r.status_code == 503 and r.json()["detail"]["code"] == "ELIGIBILITY_UNAVAILABLE"


# ─── ownership and authentication ────────────────────────────────────────────

class TestOwnership:
    def test_each_farmer_gets_their_own_profile_result(self, env):
        a, b = env.farmer("a@example.com"), env.farmer("b@example.com")
        a.put({**BASE, "age": 30})
        b.put({"state": "Punjab", "consent_given": True})
        assert status_of(elig(a, page_size=50), "KA_SCHEME") == "ELIGIBLE"
        assert status_of(elig(b, page_size=50), "KA_SCHEME") == "NOT_ELIGIBLE"
        assert status_of(elig(b, page_size=50), "AGE_SCHEME") == "NEEDS_MORE_INFORMATION"

    @pytest.mark.parametrize("method,path", [
        ("get", "/farmers/me/eligibility"), ("get", "/farmers/me/eligibility/basis"),
        ("get", "/farmers/me/search-history"), ("delete", "/farmers/me/search-history"),
        ("delete", "/farmers/me/search-history/1"),
    ])
    def test_signed_out_is_401(self, env, method, path):
        from fastapi.testclient import TestClient
        from app.main import app
        assert getattr(TestClient(app), method)(path).status_code == 401

    def test_no_farmer_id_parameter_is_honoured(self, env):
        a, b = env.farmer("a@example.com"), env.farmer("b@example.com")
        a.put({**BASE, "age": 30})
        r = b.c.get("/farmers/me/eligibility", params={"farmer_id": a.farmer_id, "page_size": 50})
        assert status_of(r.json(), "AGE_SCHEME") == "NEEDS_MORE_INFORMATION"


# ─── search history: retention, deletion, ownership ──────────────────────────

async def _record(f: Farmer, query, n=3, lang="en"):
    return await profile_service.record_search(f.farmer_id, query, n, lang)


class TestSearchHistory:
    @pytest.mark.asyncio
    async def test_recorded_only_with_consent(self, env):
        f = env.farmer("a@example.com")
        assert await _record(f, "drip irrigation") is False              # no profile yet
        assert env.history.rows == []
        f.put(BASE)
        assert await _record(f, "  drip   irrigation \n") is True
        assert env.history.rows[0].query == "drip irrigation"
        assert await profile_service.record_search(None, "anonymous query") is False
        assert await _record(f, "   ") is False
        assert await _record(f, "x" * 500) is True and len(env.history.rows[-1].query) == 200

    @pytest.mark.asyncio
    async def test_not_recorded_for_a_profile_without_consent(self, env):
        f = env.farmer("a@example.com")
        f.put(BASE)
        p = pk(env, f)
        env.prof.rows[p] = env.prof.rows[p].model_copy(update={"consent_given": False})
        assert await _record(f, "pm kisan") is False and env.history.rows == []

    @pytest.mark.asyncio
    async def test_capped_at_max_entries_and_retention_days(self, env):
        f = env.farmer("a@example.com")
        f.put(BASE)
        p = pk(env, f)
        await env.history.add(p, "very old", 1, "en", at=env.history.now - timedelta(days=RETENTION_DAYS + 1))
        for i in range(MAX_ENTRIES + 5):
            await _record(f, f"query {i}")
        r = f.c.get("/farmers/me/search-history", params={"limit": 50})
        assert r.headers["X-Total-Count"] == str(MAX_ENTRIES)
        queries = [e["query"] for e in r.json()]
        assert queries[0] == f"query {MAX_ENTRIES + 4}" and "very old" not in queries
        assert "query 0" not in queries                                 # oldest dropped

    @pytest.mark.asyncio
    async def test_list_newest_first_with_pagination(self, env):
        f = env.farmer("a@example.com")
        f.put(BASE)
        for q in ("one", "two", "three"):
            await _record(f, q)
        r = f.c.get("/farmers/me/search-history", params={"limit": 2, "offset": 1})
        assert r.status_code == 200 and r.headers["X-Total-Count"] == "3"
        assert [e["query"] for e in r.json()] == ["two", "one"]
        for bad in ({"limit": 0}, {"limit": 51}, {"offset": -1}):
            assert f.c.get("/farmers/me/search-history", params=bad).status_code == 422

    @pytest.mark.asyncio
    async def test_delete_own_search(self, env):
        f = env.farmer("a@example.com")
        f.put(BASE)
        await _record(f, "keep me")
        await _record(f, "delete me")
        target = next(r.id for r in env.history.rows if r.query == "delete me")
        r = f.c.delete(f"/farmers/me/search-history/{target}", headers={"X-CSRF-Token": f.csrf})
        assert r.status_code == 204
        assert [e["query"] for e in f.c.get("/farmers/me/search-history").json()] == ["keep me"]
        again = f.c.delete(f"/farmers/me/search-history/{target}", headers={"X-CSRF-Token": f.csrf})
        assert again.status_code == 404

    @pytest.mark.asyncio
    async def test_cannot_delete_another_farmers_search(self, env):
        a, b = env.farmer("a@example.com"), env.farmer("b@example.com")
        a.put(BASE)
        await _record(a, "a's private search")
        a_entry = env.history.rows[0].id
        r = b.c.delete(f"/farmers/me/search-history/{a_entry}", headers={"X-CSRF-Token": b.csrf})
        assert r.status_code == 404                                     # same as "not found"
        assert [x.query for x in env.history.rows] == ["a's private search"]
        assert b.c.get("/farmers/me/search-history").json() == []

    @pytest.mark.asyncio
    async def test_clear_all_only_clears_own_history(self, env):
        a, b = env.farmer("a@example.com"), env.farmer("b@example.com")
        a.put(BASE)
        b.put(BASE)
        for q in ("a1", "a2"):
            await _record(a, q)
        await _record(b, "b1")
        r = a.c.delete("/farmers/me/search-history", headers={"X-CSRF-Token": a.csrf})
        assert r.status_code == 200 and r.json() == {"deleted": 2}
        assert a.c.get("/farmers/me/search-history").headers["X-Total-Count"] == "0"
        assert [e["query"] for e in b.c.get("/farmers/me/search-history").json()] == ["b1"]

    @pytest.mark.asyncio
    async def test_delete_requires_csrf(self, env):
        f = env.farmer("a@example.com")
        f.put(BASE)
        await _record(f, "q")
        entry = env.history.rows[0].id
        assert f.c.delete(f"/farmers/me/search-history/{entry}").status_code == 403
        assert f.c.delete("/farmers/me/search-history").status_code == 403
        assert len(env.history.rows) == 1

    @pytest.mark.parametrize("bad", ["0", "-1", "abc", "99999999999"])
    def test_invalid_entry_id_is_422(self, env, bad):
        f = env.farmer("a@example.com")
        assert f.c.delete(f"/farmers/me/search-history/{bad}",
                          headers={"X-CSRF-Token": f.csrf}).status_code == 422

    def test_chat_search_turn_is_recorded(self, env, monkeypatch):
        """A chat turn that searched schemes lands in history; a follow-up question doesn't."""
        f = env.farmer("a@example.com")
        f.put(BASE)
        state = {"response_status": "schemes_found", "response_text": "Found 2",
                 "response_schemes": [{"scheme_id": "A"}, {"scheme_id": "B"}], "messages": []}

        class FakeGraph:
            async def aget_state(self, config):
                return SimpleNamespace(values={})

            async def ainvoke(self, inputs, config):
                return dict(state)

        monkeypatch.setattr("app.api.chat.kisan_agent", FakeGraph())
        r = f.c.post("/chat", json={"message": "schemes for ragi farmers", "language": "en"},
                     headers={"X-CSRF-Token": f.csrf})
        assert r.status_code == 200, r.text
        assert [(x.query, x.results_count) for x in env.history.rows] == [("schemes for ragi farmers", 2)]

        state.update(response_status="asking_question", response_schemes=[])
        f.c.post("/chat", json={"message": "what is my age?", "language": "en"},
                 headers={"X-CSRF-Token": f.csrf})
        assert len(env.history.rows) == 1
