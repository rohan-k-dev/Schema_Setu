"""
Integration tests: deletion and retention against PostgreSQL (docs/PRIVACY.md).

Two farmers get a row in EVERY per-farmer table; deleting one account must remove all of
theirs (and anonymise their review cases) while leaving the other farmer's data untouched.
Also: category deletes, a deleted reviewer's open cases returning to the queue, the last
administrator rule, the audit event (account id only, valid hash chain) and the retention purge.

Opt-in, like test_auth_repository_pg.py (throw-away database; tables are truncated):
    TEST_DATABASE_URL=postgresql://schemesetu:schemesetu@localhost:5432/schemesetu_auth_test \
        python -m pytest app/tests/test_privacy_pg.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.permissions import Principal, Role, permissions_for
from app.tests.test_auth_repository_pg import TEST_URL, _alembic
from app.tests.test_review_pg import _scalar, run

pytestmark = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL not set (PostgreSQL integration)")

PER_FARMER_TABLES = ("farmer_profiles", "search_history", "saved_schemes", "saved_scheme_checklist_items",
                     "scheme_subscriptions", "notification_preferences", "notifications", "notification_deliveries",
                     "auth_sessions", "auth_tokens", "refresh_tokens")


@pytest.fixture(scope="module", autouse=True)
def migrated_db():
    _alembic("upgrade", "head")
    yield


async def _exec(q, params=()):
    from app.database.connection import get_db_connection
    async with get_db_connection() as conn:
        cur = await conn.execute(q, params)
        await conn.commit()
        return cur


def _actor(f, label=None):
    return Principal(role=Role.FARMER, label=label or f.email, account_pk=f.id, farmer_id=f.farmer_id,
                     permissions=permissions_for(Role.FARMER))


async def _farmer_with_everything(email, session):
    """An account with data in every per-farmer table, plus a linked review case."""
    from app.database.repositories import auth_repository as auth
    from app.database.repositories import profile_repository, search_history_repository
    from app.services import review_workflow as wf
    from app.tests.test_review_workflow import escalate
    f = await auth.create_farmer(email, "h", "Name " + email, None)
    now = datetime.now(timezone.utc)
    await profile_repository.save_profile(f.id, {"state": "Karnataka", "age": 40, "consent_given": True,
                                                 "consent_given_at": now}, None)
    await search_history_repository.add(f.id, f"search by {email}", 2, "en")
    saved = await _exec("INSERT INTO saved_schemes (farmer_id, scheme_id, scheme_name) VALUES (%s, 'PM_KISAN', "
                        "'PM-KISAN') RETURNING id", (f.id,))
    sid = (await saved.fetchone())[0]
    await _exec("INSERT INTO saved_scheme_checklist_items (farmer_id, saved_scheme_id, label, source, category, "
                "item_key) VALUES (%s, %s, 'Aadhaar', 'SCHEME', 'DOCUMENT', 'doc:aadhaar')", (f.id, sid))
    await _exec("INSERT INTO scheme_subscriptions (farmer_id, scheme_id) VALUES (%s, 'PM_KISAN')", (f.id,))
    await _exec("INSERT INTO notification_preferences (farmer_id) VALUES (%s)", (f.id,))
    n = await _exec("INSERT INTO notifications (farmer_id, scheme_id, change_ids, title, body, consequential, "
                    "dedupe_key) VALUES (%s, 'PM_KISAN', '[]', 't', 'b', false, %s) RETURNING id", (f.id, f"k{f.id}"))
    nid = (await n.fetchone())[0]
    await _exec("INSERT INTO notification_deliveries (notification_id, farmer_id, channel) VALUES (%s, %s, 'EMAIL')",
                (nid, f.id))
    await auth.create_session(f.id, f"sess-{f.id}", "ua", "10.0.0.1", now + timedelta(hours=1))
    await auth.create_token(f.id, "verify_email", f"tok-{f.id}", now + timedelta(hours=1))
    await _exec("INSERT INTO refresh_tokens (farmer_id, token_hash, expires_at) VALUES (%s, %s, %s)",
                (f.id, f"rt-{f.id}", now + timedelta(days=1)))
    await _exec("UPDATE farmers SET phone = %s, phone_verified_at = now() WHERE id = %s",
                (f"+9198765432{f.id % 100:02d}", f.id))
    case = await escalate(session=session)
    await wf.link_farmer(case["case_id"], f.id)
    return f, case["case_id"]


async def _rows(table, pk):
    return await _scalar(f"SELECT count(*) FROM {table} WHERE farmer_id = %s", (pk,))  # noqa: S608 (test)


def test_account_deletion_removes_every_row_and_spares_others():
    async def body():
        from app.database.repositories import audit_repository, privacy_repository as repo
        a, case_a = await _farmer_with_everything("a@example.com", "chat-a")
        b, case_b = await _farmer_with_everything("b@example.com", "chat-b")
        before = {t: await _rows(t, a.id) for t in PER_FARMER_TABLES}
        result = await repo.delete_account(a.id, _actor(a, f"account:{a.farmer_id}"))
        after_a = {t: await _rows(t, a.id) for t in PER_FARMER_TABLES}
        after_b = {t: await _rows(t, b.id) for t in PER_FARMER_TABLES}
        account = await _scalar("SELECT count(*) FROM farmers WHERE id = %s", (a.id,))
        case = await _scalar("SELECT row_to_json(c) FROM review_cases c WHERE case_id = %s", (case_a,))
        case_b_link = await _scalar("SELECT farmer_id FROM review_cases WHERE case_id = %s", (case_b,))
        event = await _scalar("SELECT row_to_json(e) FROM audit_events e WHERE action = 'ACCOUNT_DELETED'")
        return before, result, after_a, after_b, account, case, case_b_link, b.id, event, \
            await audit_repository.verify_chain()
    before, result, after_a, after_b, account, case, case_b_link, b_pk, event, chain = run(body)
    assert all(v >= 1 for v in before.values()), before                     # every table had data
    assert all(v == 0 for v in after_a.values()), after_a                   # …and all of it is gone
    assert all(v >= 1 for v in after_b.values()), after_b                   # the other farmer is untouched
    assert account == 0 and result["deleted"] and result["chat_threads"] == ["chat-a"]
    assert case["farmer_id"] is None and case["query"] == "" and case["profile_snapshot"] == {}
    assert case_b_link == b_pk
    assert event["actor_label"].startswith("account:") and "a@example.com" not in str(event) and chain["valid"]


def test_category_deletes_touch_only_their_category():
    async def body():
        from app.database.repositories import privacy_repository as repo
        a, _ = await _farmer_with_everything("a@example.com", "chat-a")
        out1 = await repo.delete_profile(a.id, _actor(a))
        out2 = await repo.delete_saved_schemes(a.id, _actor(a))
        out3 = await repo.delete_notification_data(a.id, _actor(a))
        left = {t: await _rows(t, a.id) for t in PER_FARMER_TABLES}
        phone = await _scalar("SELECT phone FROM farmers WHERE id = %s", (a.id,))
        return out1, out2, out3, left, phone
    out1, out2, out3, left, phone = run(body)
    assert out1 == {"profile": 1, "search_history": 1} and out2 == {"saved_schemes": 1, "checklist_items": 1}
    assert out3["scheme_subscriptions"] == 1 and out3["notifications"] == 1 and out3["phone"] == 1 and phone is None
    for t in ("farmer_profiles", "search_history", "saved_schemes", "saved_scheme_checklist_items",
              "scheme_subscriptions", "notification_preferences", "notifications", "notification_deliveries"):
        assert left[t] == 0, t
    assert left["auth_sessions"] == 1                                         # still signed in


def test_deleted_reviewer_releases_open_cases_and_last_admin_is_kept():
    async def body():
        from app.database.repositories import admin_repository, auth_repository as auth
        from app.database.repositories import privacy_repository as repo
        from app.services import review_workflow as wf
        from app.tests.test_review_workflow import escalate
        cli = Principal(role=None, label="cli", via="cli")
        r = await auth.create_farmer("rev@example.com", "h", None, None)
        await _exec("UPDATE farmers SET is_verified = true WHERE id = %s", (r.id,))
        await admin_repository.set_role(cli, r.farmer_id, Role.REVIEWER, None)
        await admin_repository.set_reviewer_approval(cli, r.farmer_id, True)
        reviewer = Principal.for_account(await auth.get_farmer_by_email("rev@example.com"))
        case = await escalate(session="rv")
        await wf.claim(reviewer, case["case_id"])
        await repo.delete_account(r.id, _actor(r))
        released = await _scalar("SELECT status || '/' || coalesce(assignee, '-') FROM review_cases "
                                  "WHERE case_id = %s", (case["case_id"],))
        last = await auth.create_farmer("admin@example.com", "h", None, None)
        await admin_repository.set_role(cli, last.farmer_id, Role.ADMIN, None)
        try:
            await repo.delete_account(last.id, _actor(last))
            refused = False
        except repo.LastAdmin:
            refused = True
        return released, refused, await _scalar("SELECT count(*) FROM farmers WHERE id = %s", (last.id,))
    released, refused, kept = run(body)
    assert released == "PENDING/-" and refused and kept == 1


def test_retention_purge():
    async def body():
        from app.database.repositories import privacy_repository as repo
        a, case_id = await _farmer_with_everything("a@example.com", "chat-a")
        old = "now() - interval '400 days'"
        await _exec(f"UPDATE auth_sessions SET created_at = {old}, expires_at = {old}, last_seen_at = {old} "  # noqa: S608
                    "WHERE farmer_id = %s", (a.id,))
        await _exec(f"UPDATE auth_tokens SET created_at = {old}, expires_at = {old} WHERE farmer_id = %s", (a.id,))  # noqa: S608
        await _exec(f"UPDATE notifications SET created_at = {old} WHERE farmer_id = %s", (a.id,))  # noqa: S608
        await _exec(f"UPDATE search_history SET searched_at = {old} WHERE farmer_id = %s", (a.id,))  # noqa: S608
        await _exec("UPDATE review_cases SET status = 'DISMISSED', reviewer_id = 'r' WHERE case_id = %s", (case_id,))
        await _exec(f"UPDATE review_cases SET updated_at = {old} WHERE case_id = %s", (case_id,))  # noqa: S608
        fresh = await _farmer_with_everything("b@example.com", "chat-b")
        out = await repo.purge_expired(30, 7, 365, 365, 90)
        case = await _scalar("SELECT row_to_json(c) FROM review_cases c WHERE case_id = %s", (case_id,))
        left = {t: await _rows(t, a.id) for t in ("auth_sessions", "auth_tokens", "notifications", "search_history")}
        kept_b = {t: await _rows(t, fresh[0].id) for t in ("auth_sessions", "auth_tokens", "notifications",
                                                            "search_history")}
        return out, case, left, kept_b, await _scalar("SELECT count(*) FROM farmer_profiles WHERE farmer_id = %s",
                                                     (a.id,))
    out, case, left, kept_b, profile = run(body)
    assert out["auth_sessions"] == 1 and out["auth_tokens"] == 1 and out["notifications"] == 1
    assert out["search_history"] == 1 and out["review_cases"] == 1
    assert all(v == 0 for v in left.values()) and all(v == 1 for v in kept_b.values())
    assert case["query"] == "" and case["farmer_id"] is None and case["status"] == "DISMISSED"
    assert profile == 1                                            # a profile is kept until the farmer deletes it
