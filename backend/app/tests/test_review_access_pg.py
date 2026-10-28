"""
Integration tests: the reviewer access policy against PostgreSQL (migration 0010,
docs/HUMAN_REVIEW.md) — reviewer approval and its revocation (sessions and grants ended in the
same transaction), role changes clearing approval, the approval constraint, scoped listings in
SQL, expiring / re-issued / revoked grants, and the reauthentication timestamp.

Opt-in, like test_auth_repository_pg.py (throw-away database; tables are truncated):
    TEST_DATABASE_URL=postgresql://schemesetu:schemesetu@localhost:5432/schemesetu_auth_test \
        python -m pytest app/tests/test_review_access_pg.py
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.permissions import Permission, Principal, Role, permissions_for
from app.tests.test_auth_repository_pg import TEST_URL, _alembic
from app.tests.test_review_pg import _scalar, run

pytestmark = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL not set (PostgreSQL integration)")

ADMIN = Principal(role=Role.ADMIN, label="admin@example.com", via="cli", permissions=permissions_for(Role.ADMIN))


@pytest.fixture(scope="module", autouse=True)
def migrated_db():
    _alembic("upgrade", "head")
    yield


async def _reviewer(email, approve=True):
    from app.database.repositories import admin_repository, auth_repository
    f = await auth_repository.create_farmer(email, "h", None, None)
    from app.database.connection import get_db_connection
    async with get_db_connection() as conn:
        await conn.execute("UPDATE farmers SET is_verified = true WHERE id = %s", (f.id,))
        await conn.commit()
    await admin_repository.set_role(ADMIN, f.farmer_id, Role.REVIEWER, None)
    if approve:
        await admin_repository.set_reviewer_approval(ADMIN, f.farmer_id, True)
    return await auth_repository.get_farmer_by_email(email)


def _principal(acc):
    return Principal.for_account(acc)


def test_migration_is_reversible_and_approval_needs_the_reviewer_role():
    _alembic("downgrade", "0009")
    _alembic("upgrade", "head")

    async def body():
        from app.database.connection import get_db_connection
        from app.database.repositories import auth_repository
        f = await auth_repository.create_farmer("farmer@example.com", "h", None, None)
        try:
            async with get_db_connection() as conn:
                await conn.execute("UPDATE farmers SET reviewer_approved_at = now() WHERE id = %s", (f.id,))
                await conn.commit()
            return False
        except Exception as exc:
            return "ck_farmers_reviewer_approval" in str(exc.__cause__ or exc)
    assert run(body) is True


def test_approval_revocation_ends_sessions_and_grants_together():
    async def body():
        from app.database.connection import get_db_connection
        from app.database.repositories import admin_repository, audit_repository, auth_repository
        from app.services import review_workflow as wf
        from app.tests.test_review_workflow import escalate
        r = await _reviewer("rev@example.com")
        assert _principal(r).can(Permission.REVIEW_CASE_READ)
        case = await escalate()
        await wf.grant_access(ADMIN, case["case_id"], r.email, 2)
        await auth_repository.create_session(r.id, "h1", "ua", None, datetime.now(timezone.utc) + timedelta(hours=1))
        await admin_repository.set_reviewer_approval(ADMIN, r.farmer_id, False)
        after = await auth_repository.get_farmer_by_email(r.email)
        live = await _scalar("SELECT count(*) FROM auth_sessions WHERE farmer_id = %s AND revoked_at IS NULL", (r.id,))
        grants = await _scalar("SELECT count(*) FROM review_case_grants WHERE reviewer_id = %s AND revoked_at IS NULL",
                               (r.id,))
        actions = await _scalar("SELECT array_agg(action ORDER BY id) FROM audit_events WHERE target_id = %s",
                                (r.farmer_id,))
        return after, live, grants, actions, _principal(after), await audit_repository.verify_chain()
    after, live, grants, actions, principal, chain = run(body)
    assert after.reviewer_approved_at is None and live == 0 and grants == 0
    assert actions[-2:] == ["REVIEWER_APPROVED", "REVIEWER_APPROVAL_REVOKED"] and chain["valid"]
    assert not principal.can(Permission.REVIEW_CASE_READ)


def test_role_change_clears_approval():
    async def body():
        from app.database.repositories import admin_repository, auth_repository
        r = await _reviewer("rev@example.com")
        await admin_repository.set_role(ADMIN, r.farmer_id, Role.FARMER, None)
        await admin_repository.set_role(ADMIN, r.farmer_id, Role.REVIEWER, None)
        return (await auth_repository.get_farmer_by_email(r.email)).reviewer_approved_at
    assert run(body) is None


def test_scoped_listing_and_grants_in_sql():
    async def body():
        from app.services import review_workflow as wf
        from app.tests.test_review_workflow import escalate
        a, b = await _reviewer("a@example.com"), await _reviewer("b@example.com")
        pa, pb = _principal(a), _principal(b)
        admin = ADMIN
        mine = await escalate(session="s1")
        await wf.claim(pa, mine["case_id"])
        queued = await escalate(session="s2")
        seen_by_b = {c["case_id"] for c in (await wf.list_cases(pb))["cases"]}
        denied = None
        try:
            await wf.get_case(pb, mine["case_id"])
        except wf.ReviewError as exc:
            denied = exc.status
        await wf.grant_access(admin, mine["case_id"], b.email, 1)
        granted_view = (await wf.get_case(pb, mine["case_id"]))["access"]
        with_grant = {c["case_id"] for c in (await wf.list_cases(pb))["cases"]}
        from app.database.connection import get_db_connection
        async with get_db_connection() as conn:          # let the grant expire
            await conn.execute("UPDATE review_case_grants SET granted_at = now() - interval '2 hours', "
                               "expires_at = now() - interval '1 minute'")
            await conn.commit()
        after_expiry = {c["case_id"] for c in (await wf.list_cases(pb))["cases"]}
        await wf.grant_access(admin, mine["case_id"], b.email, 1)          # re-issued after expiry
        reissued = (await wf.get_case(pb, mine["case_id"]))["access"]
        await wf.revoke_access(admin, mine["case_id"], b.email)
        rows = await _scalar("SELECT count(*) FROM review_case_grants WHERE case_id = %s", (mine["case_id"],))
        return (mine["case_id"], queued["case_id"], seen_by_b, denied, granted_view, with_grant, after_expiry,
                reissued, rows)
    mine, queued, seen, denied, granted_view, with_grant, after_expiry, reissued, rows = run(body)
    assert seen == {queued} and denied == 404
    assert granted_view == "granted" and with_grant == {mine, queued}
    assert after_expiry == {queued} and reissued == "granted" and rows == 2


def test_reauthentication_timestamp_is_stored():
    async def body():
        from app.database.repositories import auth_repository
        r = await _reviewer("rev@example.com")
        await auth_repository.create_session(r.id, "hash-1", "ua", None, datetime.now(timezone.utc) + timedelta(hours=1))
        s, _ = await auth_repository.get_live_session("hash-1")
        await auth_repository.mark_reauthenticated(s.id)
        s2, _ = await auth_repository.get_live_session("hash-1")
        return s.reauthenticated_at, s2.reauthenticated_at
    before, after = run(body)
    assert before is None and after is not None
