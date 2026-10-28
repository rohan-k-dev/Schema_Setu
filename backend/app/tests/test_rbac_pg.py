"""
Integration tests: RBAC against PostgreSQL — migration 0006 (existing accounts become
FARMER, role constraint), the append-only audit log (trigger), role / status changes
with their audit row and session revocation in one transaction, the last-admin rule
under concurrency, scheme curation audit, and the scripts/set_role.py bootstrap.

Opt-in, like test_auth_repository_pg.py (throw-away database; tables are truncated):
    TEST_DATABASE_URL=postgresql://schemesetu:schemesetu@localhost:5432/schemesetu_auth_test \
        python -m pytest app/tests/test_rbac_pg.py
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.permissions import Principal, Role, permissions_for
from app.tests.test_auth_repository_pg import TEST_URL, _alembic
from app.tests.test_saved_schemes_pg import _put_scheme, run as _run


def run(factory, truncate: bool = True):
    """Like test_saved_schemes_pg.run, also emptying audit_events (no FK to farmers, so not
    cascaded; TRUNCATE is still possible — the append-only trigger covers UPDATE / DELETE)."""
    async def body():
        if truncate:
            from app.database.connection import get_db_connection
            async with get_db_connection() as conn:
                exists = (await (await conn.execute("SELECT to_regclass('audit_events')")).fetchone())[0]
                if exists:                                     # not while downgraded to 0005
                    await conn.execute("TRUNCATE audit_events RESTART IDENTITY")
        return await factory()
    return _run(body, truncate)


pytestmark = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL not set (PostgreSQL integration)")
ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module", autouse=True)
def migrated_db():
    _alembic("upgrade", "head")
    yield


async def _accounts(*roles):
    from app.database.connection import get_db_connection
    from app.database.repositories import auth_repository as auth
    out = []
    for i, role in enumerate(roles):
        f = await auth.create_farmer(f"r{i}@example.com", "h", None, None)
        async with get_db_connection() as conn:
            await conn.execute("UPDATE farmers SET role = %s WHERE id = %s", (role, f.id))
            await conn.commit()
        out.append(f.model_copy(update={"role": role}))
    return out


def _actor(f) -> Principal:
    return Principal(role=Role(f.role), label=f.email, account_pk=f.id, farmer_id=f.farmer_id,
                     permissions=permissions_for(f.role))


async def _scalar(q, params=()):
    from app.database.connection import get_db_connection
    async with get_db_connection() as conn:
        return (await (await conn.execute(q, params)).fetchone())[0]


def test_existing_accounts_become_farmers_and_role_is_constrained():
    _alembic("downgrade", "0005")

    async def before():
        from app.database.repositories import auth_repository as auth
        await auth.create_farmer("old@example.com", "h", None, None)
    try:
        run(before)
    finally:
        _alembic("upgrade", "head")

    async def after():
        from psycopg import errors
        from app.database.connection import get_db_connection
        role = await _scalar("SELECT role FROM farmers WHERE email = 'old@example.com'")
        async with get_db_connection() as conn:
            try:
                await conn.execute("UPDATE farmers SET role = 'SUPERUSER'")
                return role, "accepted"
            except errors.CheckViolation:
                return role, "rejected"
    assert run(after, truncate=False) == ("FARMER", "rejected")


def test_audit_log_is_append_only():
    async def body():
        from app.database.connection import get_db_connection
        from app.database.repositories import audit_repository as audit
        (a,) = await _accounts("ADMIN")
        await audit.record(_actor(a), "TEST_EVENT", "x", "1", {"k": 1})
        results = []
        for q in ("UPDATE audit_events SET action = 'TAMPERED'", "DELETE FROM audit_events"):
            async with get_db_connection() as conn:
                try:
                    await conn.execute(q)
                    results.append("allowed")
                except Exception as exc:
                    results.append("append-only" in str(exc))
        rows, total = await audit.list_page(10, 0, action="TEST_EVENT")
        return results, total, rows[0].details, rows[0].actor_role
    results, total, details, role = run(body)
    assert results == [True, True] and total == 1 and details == {"k": 1} and role == "ADMIN"


def test_role_change_is_audited_and_revokes_sessions_in_one_transaction():
    async def body():
        from app.database.repositories import admin_repository as admin
        from app.database.repositories import auth_repository as auth
        a, f = await _accounts("ADMIN", "FARMER")
        await auth.create_session(f.id, "hash-1", "ua", None, datetime.now(timezone.utc) + timedelta(hours=1))
        row = await admin.set_role(_actor(a), f.farmer_id, Role.REVIEWER, Role.FARMER)
        live = await auth.get_live_session("hash-1")
        event = await _scalar("SELECT details FROM audit_events WHERE action = 'ROLE_CHANGED'")
        same = await admin.set_role(_actor(a), f.farmer_id, Role.REVIEWER, None)      # no-op: no 2nd event
        n = await _scalar("SELECT count(*) FROM audit_events")
        return row.role, live, event, same.role, n
    role, live, event, same, n = run(body)
    assert role == "REVIEWER" and live is None and event == {"from": "FARMER", "to": "REVIEWER"}
    assert same == "REVIEWER" and n == 1


def test_self_change_and_last_admin_are_refused():
    async def body():
        from app.database.repositories import admin_repository as admin
        a, b = await _accounts("ADMIN", "ADMIN")
        codes = []
        for call in (admin.set_role(_actor(a), a.farmer_id, Role.FARMER, None),
                     admin.set_active(_actor(a), a.farmer_id, False)):
            try:
                await call
            except admin.AdminRejected as exc:
                codes.append(exc.code)
        await admin.set_role(_actor(a), b.farmer_id, Role.FARMER, None)
        cli = Principal(role=None, label="cli:set_role", via="cli")
        for call in (admin.set_role(cli, a.farmer_id, Role.FARMER, None), admin.set_active(cli, a.farmer_id, False)):
            try:
                await call
            except admin.AdminRejected as exc:
                codes.append(exc.code)
        return codes, await _scalar("SELECT count(*) FROM farmers WHERE role = 'ADMIN' AND is_active")
    codes, admins = run(body)
    assert codes == ["SELF_CHANGE", "SELF_CHANGE", "LAST_ADMIN", "LAST_ADMIN"] and admins == 1


def test_two_admins_demoting_each_other_at_once_leave_one_admin():
    async def body():
        from app.database.repositories import admin_repository as admin
        a, b = await _accounts("ADMIN", "ADMIN")
        results = await asyncio.gather(admin.set_role(_actor(a), b.farmer_id, Role.FARMER, None),
                                       admin.set_role(_actor(b), a.farmer_id, Role.FARMER, None),
                                       return_exceptions=True)
        return ([type(r).__name__ for r in results],
                await _scalar("SELECT count(*) FROM farmers WHERE role = 'ADMIN' AND is_active"))
    kinds, admins = run(body)
    assert sorted(kinds) == ["AdminRejected", "FarmerRow"] and admins == 1


def test_deactivation_revokes_sessions_and_scheme_curation_is_audited():
    async def body():
        from app.database.repositories import admin_repository as admin
        from app.database.repositories import auth_repository as auth
        a, f = await _accounts("ADMIN", "FARMER")
        await auth.create_session(f.id, "hash-2", "ua", None, datetime.now(timezone.utc) + timedelta(hours=1))
        await admin.set_active(_actor(a), f.farmer_id, False)
        live = await auth.get_live_session("hash-2")
        await _put_scheme("PM_TEST")
        s = await admin.curate_scheme(_actor(a), "PM_TEST", {"status": "SUSPENDED", "review_notes": "check"})
        missing = await admin.curate_scheme(_actor(a), "NOPE", {"status": "SUSPENDED"})
        details = await _scalar("SELECT details FROM audit_events WHERE action = 'SCHEME_CURATED'")
        actions = await _scalar("SELECT array_agg(action ORDER BY id) FROM audit_events")
        return live, s.status, missing, details, actions
    live, status, missing, details, actions = run(body)
    assert live is None and status == "SUSPENDED" and missing is None
    assert details == {"before": {"status": "ACTIVE", "review_notes": None},
                       "after": {"status": "SUSPENDED", "review_notes": "check"}}
    assert actions == ["ACCOUNT_DEACTIVATED", "SCHEME_CURATED"]


def test_account_listing_filters_and_escapes_wildcards():
    async def body():
        from app.database.repositories import admin_repository as admin
        await _accounts("ADMIN", "FARMER", "REVIEWER")
        reviewers, n = await admin.list_accounts(10, 0, role="REVIEWER")
        _, wildcard = await admin.list_accounts(10, 0, query="%")
        _, named = await admin.list_accounts(10, 0, query="r1@")
        return [r.role for r in reviewers], n, wildcard, named
    assert run(body) == (["REVIEWER"], 1, 0, 1)


def test_set_role_script_bootstraps_an_admin():
    async def setup():
        from app.database.repositories import auth_repository as auth
        await auth.create_farmer("boss@example.com", "h", None, None)
    run(setup)
    env = {**os.environ, "DATABASE_URL": TEST_URL}
    script = str(ROOT / "scripts" / "set_role.py")
    ok = subprocess.run([sys.executable, script, "boss@example.com", "ADMIN"], env=env, capture_output=True, text=True)
    bad = subprocess.run([sys.executable, script, "nobody@example.com", "ADMIN"], env=env, capture_output=True, text=True)
    last = subprocess.run([sys.executable, script, "boss@example.com", "FARMER"], env=env, capture_output=True, text=True)

    async def check():
        return (await _scalar("SELECT role FROM farmers WHERE email = 'boss@example.com'"),
                await _scalar("SELECT actor_label FROM audit_events WHERE action = 'ROLE_CHANGED'"))
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert bad.returncode == 1 and "No account" in bad.stdout
    assert last.returncode == 1 and "last active administrator" in last.stdout
    assert run(check, truncate=False) == ("ADMIN", "cli:set_role")
