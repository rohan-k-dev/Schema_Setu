"""
Saved schemes + application checklists through the real HTTP API with real cookie
sessions for two farmers: saving / unsaving, duplicate saves, checklist progress and
notes, the optional application reference, the farmer's own milestones, scheme updates
(version change → checklist sync + notice), the user-reported label, and cross-user
access. An in-memory store stands in for PostgreSQL; the SQL itself is covered by
test_saved_schemes_pg.py.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import DatabaseError
from app.core.rate_limit import limiter
from app.database.repositories import saved_scheme_repository as real_repo
from app.database.repositories.saved_scheme_repository import SchemeContent
from app.main import app
from app.models.db import ApplicationStepRow, SchemeDocumentRow, SchemeRow
from app.models.db.farmer_auth import ChecklistItemRow, SavedSchemeRow
from app.models.saved_scheme_schemas import PROGRESS_NOTICE
from app.services import saved_scheme_service as svc
from app.tests.fake_auth_repo import FakeAuthRepo
from app.tests.test_profile_module import ORIGIN, UA, FakeProfileRepo, Farmer


def _now():
    return datetime.now(timezone.utc)


class FakeSavedRepo:
    """saved_scheme_repository in memory, with the same ownership and duplicate semantics."""

    ItemSpec = real_repo.ItemSpec
    MilestoneLimit = real_repo.MilestoneLimit
    MAX_USER_MILESTONES = real_repo.MAX_USER_MILESTONES

    def __init__(self):
        self.down = False
        self.schemes: dict[str, SchemeContent] = {}
        self.saved: dict[int, SavedSchemeRow] = {}
        self.items: dict[int, ChecklistItemRow] = {}
        self._ids = itertools.count(1)

    # scheme data
    def put_scheme(self, sid, docs=(("Aadhaar Card", True), ("Land Records", True)),
                   steps=("Visit the PM-KISAN portal or CSC", "Register with bank details"),
                   status="ACTIVE", data_version="1.0", name=None):
        pk = next(self._ids)                     # new ids on every "import", like the real importer
        self.schemes[sid] = SchemeContent(
            SchemeRow(id=pk, scheme_id=sid, name=name or f"Scheme {sid}", description="d", status=status,
                      data_version=data_version, official_url=f"https://example.gov.in/{sid}"),
            [SchemeDocumentRow(id=next(self._ids), scheme_id=pk, name=n, mandatory=m, document_order=i)
             for i, (n, m) in enumerate(docs)],
            [ApplicationStepRow(id=next(self._ids), scheme_id=pk, step_number=i + 1, description=d, mode="ONLINE")
             for i, d in enumerate(steps)])

    def _check(self):
        if self.down:
            raise DatabaseError("Could not connect to database: secret-host:5432")

    async def load_scheme_content(self, ids):
        self._check()
        return {i: self.schemes[i] for i in ids if i in self.schemes}

    # saved schemes
    def _mine(self, pk, sid):
        return next((r for r in self.saved.values() if r.farmer_id == pk and r.scheme_id == sid), None)

    async def list_saved(self, pk):
        self._check()
        return sorted((r for r in self.saved.values() if r.farmer_id == pk), key=lambda r: -r.id)

    async def get_saved(self, pk, sid):
        self._check()
        return self._mine(pk, sid)

    async def list_items(self, pk, saved_ids):
        return sorted((i for i in self.items.values() if i.farmer_id == pk and i.saved_scheme_id in saved_ids),
                      key=lambda i: (i.saved_scheme_id, i.position, i.id))

    def _add_item(self, saved, spec, version):
        iid = next(self._ids)
        self.items[iid] = ChecklistItemRow(id=iid, saved_scheme_id=saved.id, farmer_id=saved.farmer_id,
                                           item_key=spec.key, category=spec.category, source="SCHEME",
                                           label=spec.label, detail=spec.detail, position=spec.position,
                                           introduced_in_version=version)

    async def create_saved(self, pk, sid, name, status, notes, version, data_version, items):
        self._check()
        existing = self._mine(pk, sid)
        if existing:
            return existing, False
        row = SavedSchemeRow(id=next(self._ids), farmer_id=pk, scheme_id=sid, scheme_name=name,
                             eligibility_status=status, notes=notes, saved_at=_now(), scheme_version=version,
                             saved_scheme_version=version, scheme_data_version=data_version)
        self.saved[row.id] = row
        for s in items:
            self._add_item(row, s, version)
        return row, True

    async def sync_scheme_items(self, pk, saved_id, expected, new, data_version, name, items):
        row = self.saved.get(saved_id)
        if not row or row.farmer_id != pk or row.scheme_version != expected:
            return False
        mine = {i.item_key: i for i in self.items.values() if i.saved_scheme_id == saved_id and i.source == "SCHEME"}
        for s in items:
            if s.key in mine:
                self.items[mine[s.key].id] = mine[s.key].model_copy(update=dict(
                    category=s.category, label=s.label, detail=s.detail, position=s.position,
                    removed_in_version=None))
            else:
                self._add_item(row, s, new)
        for k, i in mine.items():
            if k not in {s.key for s in items} and i.removed_in_version is None:
                self.items[i.id] = i.model_copy(update={"removed_in_version": new})
        first = expected is None
        self.saved[saved_id] = row.model_copy(update=dict(
            scheme_version=new, scheme_data_version=data_version, scheme_name=name,
            saved_scheme_version=row.saved_scheme_version or new,
            previous_scheme_version=row.previous_scheme_version if first else expected,
            scheme_changed_at=row.scheme_changed_at if first else _now(),
            scheme_update_seen=row.scheme_update_seen if first else False))
        return True

    async def delete_saved(self, pk, sid):
        row = self._mine(pk, sid)
        if not row:
            return False
        del self.saved[row.id]
        self.items = {k: i for k, i in self.items.items() if i.saved_scheme_id != row.id}
        return True

    async def update_saved(self, pk, sid, changes):
        assert set(changes) <= set(real_repo.SAVED_EDITABLE)
        row = self._mine(pk, sid)
        if not row:
            return None
        self.saved[row.id] = row = row.model_copy(update=changes)
        return row

    def _item_of(self, pk, sid, item_id):
        row = self._mine(pk, sid)
        i = self.items.get(item_id)
        return i if row and i and i.saved_scheme_id == row.id and i.farmer_id == pk else None

    async def update_item(self, pk, sid, item_id, changes):
        assert set(changes) <= set(real_repo.ITEM_EDITABLE)
        i = self._item_of(pk, sid, item_id)
        if not i:
            return None
        if "completed" in changes:
            changes = {**changes, "completed_at": (i.completed_at or _now()) if changes["completed"] else None}
        self.items[i.id] = i = i.model_copy(update=changes)
        return i

    async def add_milestone(self, pk, sid, key, label, note, completed):
        row = self._mine(pk, sid)
        if not row:
            return None
        if sum(1 for i in self.items.values() if i.saved_scheme_id == row.id and i.source == "USER") \
                >= self.MAX_USER_MILESTONES:
            raise self.MilestoneLimit()
        iid = next(self._ids)
        self.items[iid] = ChecklistItemRow(id=iid, saved_scheme_id=row.id, farmer_id=pk, item_key=key,
                                           category="MILESTONE", source="USER", label=label, note=note,
                                           position=9001 + iid, completed=completed,
                                           completed_at=_now() if completed else None)
        return self.items[iid]

    async def get_item(self, pk, sid, item_id):
        return self._item_of(pk, sid, item_id)

    async def delete_milestone(self, pk, sid, item_id):
        i = self._item_of(pk, sid, item_id)
        if not i or i.source != "USER":
            return False
        del self.items[i.id]
        return True


@pytest.fixture
def env(monkeypatch):
    auth = FakeAuthRepo()
    repo = FakeSavedRepo()
    for sid in ("PM_KISAN", "PMFBY"):
        repo.put_scheme(sid)
    monkeypatch.setattr("app.services.auth_service.repo", auth)
    monkeypatch.setattr("app.services.saved_scheme_service.repo", repo)
    monkeypatch.setattr("app.services.saved_scheme_service.profile_repo", FakeProfileRepo(auth))
    monkeypatch.setattr("app.api.auth.is_db_available", lambda: True)
    monkeypatch.setattr("app.api.deps.is_db_available", lambda: True)
    for name in ("send_password_reset_email",
                 "send_account_exists_email", "send_password_changed_email"):
        async def _noop(*a, **k):
            return True
        monkeypatch.setattr(f"app.services.auth_service.email_service.{name}", _noop)
    limiter.reset()
    yield SimpleNamespace(auth=auth, repo=repo, farmer=lambda email: User(auth, email))
    limiter.reset()


class User(Farmer):
    def _h(self, csrf):
        return {"X-CSRF-Token": self.csrf} if csrf else {}

    def save(self, scheme_id="PM_KISAN", csrf=True, **body):
        return self.c.post("/farmers/me/saved-schemes", json={"scheme_id": scheme_id, **body},
                           headers=self._h(csrf))

    def list(self):
        r = self.c.get("/farmers/me/saved-schemes")
        assert r.status_code == 200, r.text
        return r.json()

    def detail(self, sid="PM_KISAN"):
        return self.c.get(f"/farmers/me/saved-schemes/{sid}")

    def patch(self, body, sid="PM_KISAN", csrf=True):
        return self.c.patch(f"/farmers/me/saved-schemes/{sid}", json=body, headers=self._h(csrf))

    def tick(self, item_id, body, sid="PM_KISAN", csrf=True):
        return self.c.patch(f"/farmers/me/saved-schemes/{sid}/checklist/{item_id}", json=body,
                            headers=self._h(csrf))

    def milestone(self, body, sid="PM_KISAN"):
        return self.c.post(f"/farmers/me/saved-schemes/{sid}/checklist", json=body, headers=self._h(True))

    def drop(self, item_id, sid="PM_KISAN"):
        return self.c.delete(f"/farmers/me/saved-schemes/{sid}/checklist/{item_id}", headers=self._h(True))

    def unsave(self, sid="PM_KISAN", csrf=True):
        return self.c.delete(f"/farmers/me/saved-schemes/{sid}", headers=self._h(csrf))


def item(body, key=None, label=None):
    return next(i for i in body["checklist"] if (key and i["key"] == key) or (label and i["label"] == label))


# ─── save / unsave ────────────────────────────────────────────────────────────

class TestSaveAndUnsave:
    def test_save_creates_checklist_from_the_scheme(self, env):
        a = env.farmer("a@example.com")
        r = a.save(scheme_name="Client says something else", eligibility_status="ELIGIBLE")
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["created"] is True and body["scheme_name"] == "Scheme PM_KISAN"
        assert body["eligibility_status"] == "ELIGIBLE"
        cats = [i["category"] for i in body["checklist"]]
        assert cats == ["DOCUMENT", "DOCUMENT", "PREPARATION", "PREPARATION", "APPLICATION", "APPLICATION",
                        "SUBMISSION", "ACKNOWLEDGEMENT"]
        assert item(body, label="Aadhaar Card")["detail"] == "Required"
        assert item(body, label="Register with bank details")["detail"] == "Online"
        assert all(i["source"] == "SCHEME" and not i["completed"] for i in body["checklist"])
        assert body["progress"] == {"completed": 0, "total": 8, "stage": "NOT_STARTED", "reported_by": "FARMER"}
        assert len(body["scheme_version"]) == svc.SHORT_VERSION
        assert body["application_reference"] is None

    def test_progress_is_labelled_user_reported(self, env):
        a = env.farmer("a@example.com")
        body = a.save().json()
        assert body["progress_source"] == "USER_REPORTED" and body["official_tracking"] is False
        assert body["progress_notice"] == PROGRESS_NOTICE and "not connected" in PROGRESS_NOTICE
        assert a.list()[0]["progress_source"] == "USER_REPORTED"

    def test_scheme_without_documents_or_steps_still_gets_a_useful_checklist(self, env):
        env.repo.put_scheme("ENAM", docs=(), steps=())
        body = env.farmer("a@example.com").save("ENAM").json()
        keys = [i["key"] for i in body["checklist"]]
        assert keys == ["doc:official-list", "prep:eligibility", "prep:copies", "app:find-process",
                        "submit:application", "ack:received"]

    def test_duplicate_save_changes_nothing(self, env):
        a = env.farmer("a@example.com")
        first = a.save(notes="Ask at the bank").json()
        a.tick(first["checklist"][0]["id"], {"completed": True})
        r = a.save(notes="overwritten?")
        assert r.status_code == 200 and r.json()["created"] is False
        again = r.json()
        assert again["notes"] == "Ask at the bank" and again["saved_at"] == first["saved_at"]
        assert again["checklist"][0]["completed"] is True
        assert len(again["checklist"]) == 8 and len(a.list()) == 1
        assert len(env.repo.items) == 8

    def test_unsave_removes_scheme_and_checklist(self, env):
        a = env.farmer("a@example.com")
        a.save()
        a.save("PMFBY")
        assert a.unsave().status_code == 204
        assert [s["scheme_id"] for s in a.list()] == ["PMFBY"]
        assert a.detail().status_code == 404
        assert a.unsave().status_code == 404
        assert len(env.repo.items) == 8                 # only PMFBY's checklist is left
        r = a.save()                                     # saving again starts a fresh checklist
        assert r.status_code == 201 and r.json()["progress"]["completed"] == 0

    def test_only_schemes_in_the_database_can_be_saved(self, env):
        a = env.farmer("a@example.com")
        r = a.save("WEB_RESULT_123")
        assert r.status_code == 404 and r.json()["detail"]["code"] == "SCHEME_NOT_FOUND"
        env.repo.put_scheme("OLD", status="INACTIVE")
        assert a.save("OLD").status_code == 409
        assert a.list() == []

    @pytest.mark.parametrize("body", [
        {"scheme_id": "PM KISAN"},                                     # pattern
        {"scheme_id": ""},
        {"scheme_id": "PM_KISAN", "eligibility_status": "MAYBE"},
        {"scheme_id": "PM_KISAN", "notes": "x" * 1001},
        {"scheme_id": "PM_KISAN", "farmer_id": "uuid-2"},              # unexpected field
    ])
    def test_invalid_save_requests_rejected(self, env, body):
        a = env.farmer("a@example.com")
        assert a.c.post("/farmers/me/saved-schemes", json=body,
                        headers={"X-CSRF-Token": a.csrf}).status_code == 422
        assert a.list() == []


# ─── checklist progress ───────────────────────────────────────────────────────

class TestChecklist:
    def test_mark_complete_incomplete_and_notes_persist(self, env):
        a = env.farmer("a@example.com")
        doc = a.save().json()["checklist"][0]
        r = a.tick(doc["id"], {"completed": True, "note": "Original and 2 copies"})
        assert r.status_code == 200
        stored = item(a.detail().json(), key=doc["key"])
        assert stored["completed"] and stored["completed_at"] and stored["note"] == "Original and 2 copies"
        assert a.detail().json()["progress"]["stage"] == "PREPARING"

        a.tick(doc["id"], {"completed": False})
        stored = item(a.detail().json(), key=doc["key"])
        assert not stored["completed"] and stored["completed_at"] is None
        assert stored["note"] == "Original and 2 copies"                   # note untouched
        a.tick(doc["id"], {"note": None})
        assert item(a.detail().json(), key=doc["key"])["note"] is None

    def test_repeated_tick_is_idempotent(self, env):
        a = env.farmer("a@example.com")
        doc = a.save().json()["checklist"][0]
        first = a.tick(doc["id"], {"completed": True}).json()
        second = a.tick(doc["id"], {"completed": True}).json()
        assert item(first, key=doc["key"])["completed_at"] == item(second, key=doc["key"])["completed_at"]
        assert second["progress"]["completed"] == 1

    def test_stage_follows_submission_and_acknowledgement(self, env):
        a = env.farmer("a@example.com")
        body = a.save().json()
        a.tick(item(body, key="submit:application")["id"], {"completed": True})
        assert a.detail().json()["progress"]["stage"] == "SUBMITTED"
        a.tick(item(body, key="ack:received")["id"], {"completed": True})
        d = a.detail().json()
        assert d["progress"] == {"completed": 2, "total": 8, "stage": "ACKNOWLEDGED", "reported_by": "FARMER"}

    @pytest.mark.parametrize("body", [{}, {"completed": None}, {"completed": "yes"}, {"note": "x" * 501},
                                      {"note": "   "}, {"completed": True, "verified_by": "officer"}])
    def test_invalid_item_updates_rejected(self, env, body):
        a = env.farmer("a@example.com")
        doc = a.save().json()["checklist"][0]
        assert a.tick(doc["id"], body).status_code == 422
        assert not item(a.detail().json(), key=doc["key"])["completed"]

    def test_application_reference_only_if_the_farmer_gives_one(self, env):
        a = env.farmer("a@example.com")
        assert a.save().json()["application_reference"] is None
        r = a.patch({"application_reference": " PMK/2026/000123 "})
        assert r.status_code == 200 and r.json()["application_reference"] == "PMK/2026/000123"
        for bad in ("<script>", "x" * 65, "", "a\nb"):
            assert a.patch({"application_reference": bad}).status_code == 422
        assert a.patch({"application_reference": None}).json()["application_reference"] is None
        r = a.patch({"notes": "Bank: SBI Mandya"})
        assert r.json()["notes"] == "Bank: SBI Mandya" and r.json()["application_reference"] is None
        assert a.patch({}).status_code == 422
        assert a.patch({"notes": "x"}, sid="PMFBY").status_code == 404     # not saved

    def test_own_milestones_add_tick_delete(self, env):
        a = env.farmer("a@example.com")
        a.save()
        r = a.milestone({"label": "Field verification visit done", "completed": True})
        assert r.status_code == 201
        m = r.json()["checklist"][-1]
        assert (m["source"], m["category"], m["completed"]) == ("USER", "MILESTONE", True)
        assert r.json()["progress"]["total"] == 9
        assert a.tick(m["id"], {"completed": False}).status_code == 200
        r = a.drop(m["id"])
        assert r.status_code == 200 and len(r.json()["checklist"]) == 8
        assert a.drop(m["id"]).status_code == 404

    def test_scheme_items_cannot_be_deleted(self, env):
        a = env.farmer("a@example.com")
        doc = a.save().json()["checklist"][0]
        r = a.drop(doc["id"])
        assert r.status_code == 409 and r.json()["detail"]["code"] == "NOT_DELETABLE"

    def test_milestone_limit_and_validation(self, env):
        a = env.farmer("a@example.com")
        a.save()
        for i in range(real_repo.MAX_USER_MILESTONES):
            assert a.milestone({"label": f"Step {i}"}).status_code == 201
        r = a.milestone({"label": "one too many"})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "LIMIT_REACHED"
        for bad in ({"label": ""}, {"label": "  "}, {"label": "x" * 121}, {"label": "ok", "source": "SCHEME"}):
            assert a.milestone(bad).status_code == 422
        assert a.milestone({"label": "x"}, sid="PMFBY").status_code == 404


# ─── scheme updates (version) ─────────────────────────────────────────────────

class TestSchemeUpdates:
    def test_reimport_with_same_content_keeps_version_and_progress(self, env):
        a = env.farmer("a@example.com")
        body = a.save().json()
        a.tick(body["checklist"][0]["id"], {"completed": True})
        env.repo.put_scheme("PM_KISAN")                               # new database ids, same content
        d = a.detail().json()
        assert d["scheme_version"] == body["scheme_version"] and d["update_notice"] is None
        assert d["progress"]["completed"] == 1

    def test_changed_scheme_syncs_checklist_and_shows_notice(self, env):
        a = env.farmer("a@example.com")
        body = a.save().json()
        a.tick(item(body, label="Aadhaar Card")["id"], {"completed": True})
        a.tick(item(body, label="Land Records")["id"], {"completed": True, "note": "got it"})
        a.patch({"application_reference": "REF1"})
        env.repo.put_scheme("PM_KISAN", docs=(("Aadhaar Card", True), ("Bank Passbook", False)),
                            data_version="1.1", name="PM-KISAN (renamed)")

        listed = a.list()[0]                                           # the list syncs too
        assert listed["update_notice"]["added"] == ["Bank Passbook"]
        d = a.detail().json()
        assert d["scheme_name"] == "PM-KISAN (renamed)" and d["scheme_data_version"] == "1.1"
        assert d["scheme_version"] != body["scheme_version"]
        assert d["saved_scheme_version"] == body["scheme_version"]     # what it was saved with
        assert item(d, label="Aadhaar Card")["completed"] and item(d, label="Aadhaar Card")["current"]
        land = item(d, label="Land Records")
        assert land["completed"] and land["note"] == "got it" and land["current"] is False
        bank = item(d, label="Bank Passbook")
        assert bank["added_in_update"] and bank["detail"] == "Needed in some cases"
        assert d["update_notice"]["removed"] == ["Land Records"]
        assert d["progress"]["completed"] == 1 and d["progress"]["total"] == 8
        assert d["application_reference"] == "REF1"

        acked = a.patch({"acknowledge_scheme_update": True}).json()
        assert acked["update_notice"] is None
        assert a.patch({"acknowledge_scheme_update": False}).status_code == 422

    def test_scheme_removed_from_database_keeps_the_farmers_record(self, env):
        a = env.farmer("a@example.com")
        body = a.save().json()
        a.tick(body["checklist"][0]["id"], {"completed": True})
        del env.repo.schemes["PM_KISAN"]
        d = a.detail().json()
        assert d["scheme_available"] is False and d["scheme_status"] is None
        assert d["progress"]["completed"] == 1 and len(d["checklist"]) == 8

    def test_database_outage_gives_503_without_internal_details(self, env):
        a = env.farmer("a@example.com")
        a.save()
        env.repo.down = True
        r = a.c.get("/farmers/me/saved-schemes")
        assert r.status_code == 503 and "secret-host" not in r.text
        assert a.save("PMFBY").status_code == 503


# ─── ownership ────────────────────────────────────────────────────────────────

class TestCrossUser:
    def test_each_farmer_sees_only_their_own_saved_schemes(self, env):
        a, b = env.farmer("a@example.com"), env.farmer("b@example.com")
        a.save()
        a.save("PMFBY")
        b.save("PMFBY")
        assert [s["scheme_id"] for s in a.list()] == ["PMFBY", "PM_KISAN"]
        assert [s["scheme_id"] for s in b.list()] == ["PMFBY"]
        assert b.detail("PM_KISAN").status_code == 404

    def test_other_farmers_items_cannot_be_changed_or_deleted(self, env):
        a, b = env.farmer("a@example.com"), env.farmer("b@example.com")
        a_body = a.save().json()
        m = a.milestone({"label": "mine"}).json()["checklist"][-1]
        b.save()                                                       # b has the same scheme saved
        a_item = a_body["checklist"][0]
        assert b.tick(a_item["id"], {"completed": True}).status_code == 404
        assert b.tick(m["id"], {"note": "hijack"}).status_code == 404
        assert b.drop(m["id"]).status_code == 404
        assert b.unsave("PMFBY").status_code == 404
        d = a.detail().json()
        assert not item(d, key=a_item["key"])["completed"] and d["checklist"][-1]["note"] is None
        # a's item id under a's own other scheme path is also not found
        a.save("PMFBY")
        assert a.tick(a_item["id"], {"completed": True}, sid="PMFBY").status_code == 404

    def test_b_unsaving_does_not_affect_a(self, env):
        a, b = env.farmer("a@example.com"), env.farmer("b@example.com")
        a.save()
        b.save()
        assert b.unsave().status_code == 204
        assert a.detail().status_code == 200 and len(a.detail().json()["checklist"]) == 8

    def test_signed_out_and_csrf_less_requests_rejected(self, env):
        a = env.farmer("a@example.com")
        doc = a.save().json()["checklist"][0]
        anon = TestClient(app, headers={"User-Agent": UA, "Origin": ORIGIN})
        assert anon.get("/farmers/me/saved-schemes").status_code == 401
        assert anon.post("/farmers/me/saved-schemes", json={"scheme_id": "PMFBY"}).status_code == 401
        assert a.save("PMFBY", csrf=False).status_code == 403
        assert a.tick(doc["id"], {"completed": True}, csrf=False).status_code == 403
        assert a.patch({"notes": "x"}, csrf=False).status_code == 403
        assert a.unsave(csrf=False).status_code == 403
        assert [s["scheme_id"] for s in a.list()] == ["PM_KISAN"]
        assert not a.detail().json()["checklist"][0]["completed"]

    def test_stolen_cookie_cannot_read_saved_schemes(self, env):
        a = env.farmer("a@example.com")
        a.save()
        thief = TestClient(app, headers={"User-Agent": "curl/8"})
        thief.cookies.set("ss_session", a.c.cookies["ss_session"])
        assert thief.get("/farmers/me/saved-schemes").status_code == 401


# ─── pure functions ───────────────────────────────────────────────────────────

def test_version_ignores_database_ids_but_not_content():
    repo = FakeSavedRepo()
    repo.put_scheme("X")
    v1 = svc.scheme_version(repo.schemes["X"])
    repo.put_scheme("X")
    assert svc.scheme_version(repo.schemes["X"]) == v1
    repo.put_scheme("X", steps=("Visit the PM-KISAN portal or CSC", "Register with bank and land details"))
    assert svc.scheme_version(repo.schemes["X"]) != v1


def test_item_keys_are_stable_and_unique():
    repo = FakeSavedRepo()
    repo.put_scheme("X", docs=(("Aadhaar Card", True), ("aadhaar  card", True)))
    keys = [i.key for i in svc.build_checklist(repo.schemes["X"])]
    assert len(keys) == len(set(keys)) and sum(k.startswith("doc:") for k in keys) == 1
    assert keys == [i.key for i in svc.build_checklist(repo.schemes["X"])]
