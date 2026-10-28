"""
Integration tests: the scheme-update pipeline and notifications against PostgreSQL —
migration 0008, fingerprint dedupe, review state machine, the audience query (saved +
followed, active accounts, preferences), one notification per change set, one delivery
per channel, concurrent claiming with SKIP LOCKED (each delivery sent once), stuck
sends that are not retried, provider status updates, phone codes (attempt lock, number
already verified elsewhere), the SMS-consent constraint, and a real publish into the
test database from a temporary data folder.

Opt-in, like test_auth_repository_pg.py (throw-away database; tables are truncated):
    TEST_DATABASE_URL=postgresql://schemesetu:schemesetu@localhost:5432/schemesetu_auth_test \
        python -m pytest app/tests/test_scheme_updates_pg.py
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.permissions import Principal, Role, permissions_for
from app.tests.test_admin_ops_pg import run as _run
from app.tests.test_auth_repository_pg import TEST_URL, _alembic

pytestmark = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL not set (PostgreSQL integration)")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
ADMIN = Principal(role=Role.ADMIN, label="updates-admin@example.com", permissions=permissions_for(Role.ADMIN),
                  account_pk=None)


@pytest.fixture(scope="module", autouse=True)
def migrated_db():
    _alembic("upgrade", "head")
    _alembic("downgrade", "0007")          # 0008 is reversible
    _alembic("upgrade", "head")
    yield


def run(factory, truncate=True):
    async def body():
        if truncate:
            from app.database.connection import get_db_connection
            async with get_db_connection() as conn:
                await conn.execute("TRUNCATE scheme_change_batches, notifications RESTART IDENTITY CASCADE")
        return await factory()
    return _run(body, truncate)


async def _q(q, p=()):
    from app.database.connection import get_db_connection
    async with get_db_connection() as conn:
        cur = await conn.execute(q, p)
        rows = await cur.fetchall() if cur.description else []
        await conn.commit()
        return rows


async def _farmers(n):
    from app.database.repositories import auth_repository as auth
    out = []
    for i in range(n):
        f = await auth.create_farmer(f"n{i}@example.com", "h", None, None)
        await _q("UPDATE farmers SET is_verified = true WHERE id = %s", (f.id,))
        out.append(f)
    return out


def _change(sid="PM_KISAN", fp=None, consequential=True):
    return {"scheme_id": sid, "scheme_name": sid, "category": "ELIGIBILITY", "consequential": consequential,
            "summary": "s", "before": {"a": 1}, "after": {"a": 2}, "fingerprint": fp or uuid.uuid4().hex * 2,
            "provenance": {"source_file": "x.json"}}


def _batch():
    return {"id": str(uuid.uuid4()), "source_name": "x.json", "source_sha256": "0" * 64, "base_version": "1.0.0",
            "candidate_count": 1, "invalid_records": [], "warnings": [], "detected_by": "t", "correlation_id": None}


def test_fingerprint_dedupe_and_review_state_machine():
    async def body():
        from app.database.repositories import change_repository as repo
        fp = "a" * 64
        b1, n1, d1 = await repo.create_batch(_batch(), [_change(fp=fp)])
        b2, n2, d2 = await repo.create_batch(_batch(), [_change(fp=fp)])        # same change again
        (c,), _ = await repo.list_changes(b1["id"], "PENDING", 10, 0)
        approved = await repo.review(c["id"], "APPROVED", "admin", "checked")
        twice = await repo.review(c["id"], "REJECTED", "admin", "x")
        b3, n3, _ = await repo.create_batch(_batch(), [_change(fp=fp)])          # still APPROVED: deduped
        await repo.mark_published(b1["id"], "1.0.1")
        b4, n4, _ = await repo.create_batch(_batch(), [_change(fp=fp)])          # published → may recur later
        discarded = await repo.discard_batch(b4["id"])
        stale_review = await repo.review((await repo.list_changes(b4["id"], None, 10, 0))[0][0]["id"],
                                         "APPROVED", "a", "n")
        return (n1, d1, n2, d2, approved["status"], twice, n3, n4, discarded, stale_review,
                (await repo.get_batch(b1["id"]))["published"])
    assert run(body) == (1, 0, 0, 1, "APPROVED", None, 0, 1, True, None, 1)


def test_audience_counts_saved_and_followed_once_and_respects_preferences():
    async def body():
        from app.database.repositories import notification_repository as repo
        a, b, c, d = await _farmers(4)
        await _q("INSERT INTO saved_schemes (farmer_id, scheme_id, scheme_name) VALUES (%s, 'PM_KISAN', 'x'), "
                 "(%s, 'PM_KISAN', 'x')", (a.id, b.id))
        await repo.subscribe(b.id, "PM_KISAN")                               # saved AND followed
        await repo.subscribe(c.id, "PM_KISAN")
        await repo.save_prefs(c.id, {"email": True})
        await _q("UPDATE farmers SET is_active = false WHERE id = %s", (d.id,))
        await repo.subscribe(d.id, "PM_KISAN")                               # deactivated: excluded
        rows = await repo.audience(["PM_KISAN"])
        return [(r["farmer_pk"] - a.id, r["email"], r["in_app"]) for r in rows]
    assert run(body) == [(0, False, True), (1, False, True), (2, True, True)]


def test_one_notification_per_change_set_and_one_delivery_per_channel():
    async def body():
        from app.database.repositories import notification_repository as repo
        (a,) = await _farmers(1)
        n = {"farmer_pk": a.id, "scheme_id": "PM_KISAN", "batch_id": "b", "change_ids": [1], "title": "t",
             "body": "b", "consequential": True, "show_in_app": True, "dedupe_key": "changes:b:PM_KISAN"}
        first = await repo.create_notification(n, ["EMAIL", "SMS"])
        again = await repo.create_notification(n, ["EMAIL", "SMS"])
        counts = (await _q("SELECT count(*) FROM notifications"))[0][0], (await _q(
            "SELECT count(*) FROM notification_deliveries"))[0][0]
        return first is not None, again, counts
    assert run(body) == (True, None, (1, 2))


def test_concurrent_claims_never_overlap_and_sent_is_final():
    async def body():
        from app.database.repositories import notification_repository as repo
        farmers = await _farmers(6)
        for f in farmers:
            await repo.create_notification({"farmer_pk": f.id, "scheme_id": "S", "batch_id": "b", "change_ids": [],
                                            "title": "t", "body": "b", "consequential": False, "show_in_app": True,
                                            "dedupe_key": "k"}, ["EMAIL"])
        claims = await asyncio.gather(*[repo.claim_due(2) for _ in range(5)])
        ids = [d["id"] for batch in claims for d in batch]
        for d in ids:
            await repo.finish(d, "SENT", provider_message_id=f"m{d}")
        after = await repo.claim_due(100)                                    # nothing left to send
        await repo.finish(ids[0], "FAILED")                                  # only from SENDING: ignored
        status = (await _q("SELECT status FROM notification_deliveries WHERE id = %s", (ids[0],)))[0][0]
        return len(ids), len(set(ids)), after, status
    assert run(body) == (6, 6, [], "SENT")


def test_stuck_sending_is_given_up_not_retried_and_provider_status_is_tracked():
    async def body():
        from app.database.repositories import notification_repository as repo
        (a, b) = await _farmers(2)
        for f in (a, b):
            await repo.create_notification({"farmer_pk": f.id, "scheme_id": "S", "batch_id": "b", "change_ids": [],
                                            "title": "t", "body": "b", "consequential": False, "show_in_app": True,
                                            "dedupe_key": "k"}, ["SMS"])
        d1, d2 = await repo.claim_due(10)
        await _q("UPDATE notification_deliveries SET last_attempt_at = NOW() - interval '1 hour' WHERE id = %s",
                 (d1["id"],))
        abandoned = await repo.abandon_stuck(15)
        await repo.finish(d2["id"], "SENT", provider_message_id="prov-1")
        delivered = await repo.provider_status("prov-1", "DELIVERED", None)
        unknown = await repo.provider_status("nope", "DELIVERED", None)
        rows = dict(await _q("SELECT id, status FROM notification_deliveries"))
        return abandoned, delivered, unknown, rows[d1["id"]], rows[d2["id"]], await repo.claim_due(10)
    assert run(body) == (1, True, False, "GAVE_UP", "DELIVERED", [])


def test_phone_code_locks_and_a_number_cant_be_verified_twice():
    async def body():
        from app.database.repositories import notification_repository as repo
        a, b = await _farmers(2)
        exp = datetime.now(timezone.utc) + timedelta(minutes=10)
        await repo.create_phone_code(a.id, "right", "+919876543210", exp)
        results = [(await repo.check_phone_code(a.id, "wrong", 3))[0] for _ in range(3)]
        await repo.create_phone_code(a.id, "right2", "+919876543210", exp)
        ok = await repo.check_phone_code(a.id, "right2", 3)
        await repo.create_phone_code(b.id, "rb", "+919876543210", exp)
        try:
            await repo.check_phone_code(b.id, "rb", 3)
            taken = False
        except repo.PhoneInUse:
            taken = True
        b_phone = (await _q("SELECT phone FROM farmers WHERE id = %s", (b.id,)))[0][0]
        return results, ok, taken, b_phone
    assert run(body) == (["wrong", "wrong", "locked"], ("ok", "+919876543210"), True, None)


def test_sms_cannot_be_on_without_recorded_consent():
    async def body():
        (a,) = await _farmers(1)
        try:
            await _q("INSERT INTO notification_preferences (farmer_id, sms) VALUES (%s, true)", (a.id,))
            return "accepted"
        except Exception as exc:
            return "rejected" if "ck_pref_sms_consent" in str(exc) else str(exc)
    assert run(body) == "rejected"


def test_real_publish_into_the_database(tmp_path, monkeypatch):
    root = tmp_path / "data"
    for rel in ("validated/schemes.json", "metadata/corpus_manifest.json"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(os.path.join(ROOT, "data", rel), root / rel)
    (root / "incoming").mkdir()
    verified = json.loads((root / "validated" / "schemes.json").read_text("utf-8"))
    cand = copy.deepcopy(verified)
    pmk = next(s for s in cand if s["scheme_id"] == "PM_KISAN")
    pmk["required_documents"].append({"name": "Ration Card", "mandatory": True})
    (root / "incoming" / "scrape.json").write_text(json.dumps(cand), encoding="utf-8")
    monkeypatch.setattr("app.services.scheme_update_service.data_root", lambda: str(root))
    monkeypatch.setattr("app.services.corpus_import_service._find_corpus_path",
                        lambda: str(root / "validated" / "schemes.json"))
    monkeypatch.setattr("app.services.corpus_import_service._find_manifest_path",
                        lambda: str(root / "metadata" / "corpus_manifest.json"))

    async def body():
        from app.services import scheme_update_service as svc
        from app.services.corpus_import_service import import_corpus
        await import_corpus()                                               # the verified corpus is in the DB
        (f,) = await _farmers(1)
        await _q("INSERT INTO saved_schemes (farmer_id, scheme_id, scheme_name) VALUES (%s, 'PM_KISAN', 'x')", (f.id,))
        out = await svc.detect(ADMIN, "scrape.json")
        changes, _ = await svc.changes(ADMIN, out["batch_id"], "PENDING", 10, 0)
        await svc.review(ADMIN, changes[0]["id"], "APPROVED", "checked on the portal", False)
        result = await svc.publish(out["batch_id"], False, ADMIN)
        docs = (await _q("SELECT count(*) FROM scheme_documents d JOIN schemes s ON s.id = d.scheme_id "
                         "WHERE s.scheme_id = 'PM_KISAN' AND d.name = 'Ration Card'"))[0][0]
        version = (await _q("SELECT version FROM corpus_versions ORDER BY id DESC LIMIT 1"))[0][0]
        notes = (await _q("SELECT count(*) FROM notifications WHERE farmer_id = %s", (f.id,)))[0][0]
        again = await svc.notify(out["batch_id"], [c for c in (await svc.changes(ADMIN, out["batch_id"],
                                                                                 "PUBLISHED", 10, 0))[0]])
        return out["new_changes"], result["version"], docs, version, notes, again["created"]
    assert run(body) == (1, "1.0.1", 1, "1.0.1", 1, 0)
