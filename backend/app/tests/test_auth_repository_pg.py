"""
Integration tests: migration 0003 and the real auth repository against PostgreSQL.

Opt-in (needs a throw-away database; every table is truncated):
    TEST_DATABASE_URL=postgresql://schemesetu:schemesetu@localhost:5432/schemesetu_auth_test \
        python -m pytest app/tests/test_auth_repository_pg.py

Skipped when TEST_DATABASE_URL is not set.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

TEST_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL not set (PostgreSQL integration)")

BACKEND = Path(__file__).resolve().parents[2]


def _alembic(*args: str) -> None:
    env = {**os.environ, "DATABASE_URL": TEST_URL}
    subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, check=True,
                   capture_output=True)


@pytest.fixture(scope="module", autouse=True)
def migrated_db():
    _alembic("upgrade", "head")
    _alembic("downgrade", "0002")        # migration 0003 is reversible
    _alembic("upgrade", "head")
    yield


def run(coro_factory):
    """Run one async test body with a fresh pool on the test database."""
    from app.core.config import settings
    from app.database import connection

    async def body():
        old = settings.DATABASE_URL
        settings.DATABASE_URL = TEST_URL
        connection._pool = None
        await connection.init_db()
        try:
            async with connection.get_db_connection() as conn:
                await conn.execute("TRUNCATE farmers RESTART IDENTITY CASCADE")
            return await coro_factory()
        finally:
            await connection.close_db()
            settings.DATABASE_URL = old

    connection_mod = __import__("app.database.connection", fromlist=["x"])
    connection_mod.use_selector_event_loop_on_windows()
    return asyncio.run(body())


def _now():
    return datetime.now(tz=timezone.utc)


def test_migration_created_tables_and_columns():
    from app.database.connection import get_db_connection

    async def body():
        async with get_db_connection() as conn:
            cur = await conn.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_name IN "
                "('auth_sessions','auth_tokens')")
            tables = {r[0] for r in await cur.fetchall()}
            cur = await conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name='farmers' AND "
                "column_name IN ('failed_login_count','locked_until','password_changed_at')")
            cols = {r[0] for r in await cur.fetchall()}
        return tables, cols

    tables, cols = run(body)
    assert tables == {"auth_sessions", "auth_tokens"}
    assert cols == {"failed_login_count", "locked_until", "password_changed_at"}


def test_create_farmer_unique_email():
    from app.database.repositories import auth_repository as repo

    async def body():
        f = await repo.create_farmer("A@Example.com", "$argon2id$x", "A", None)
        dup = await repo.create_farmer("a@example.com", "$argon2id$y", "B", None)
        return f, dup, await repo.get_farmer_by_email("A@EXAMPLE.COM")

    f, dup, found = run(body)
    assert f.email == "a@example.com" and dup is None and found.id == f.id


def test_sessions_live_revoke_expire_and_revoke_all():
    from app.database.repositories import auth_repository as repo

    async def body():
        f = await repo.create_farmer("s@example.com", "h", None, None)
        await repo.create_session(f.id, "a" * 64, "u" * 64, "127.0.0.1", _now() + timedelta(hours=1))
        await repo.create_session(f.id, "b" * 64, "u" * 64, None, _now() + timedelta(hours=1))
        await repo.create_session(f.id, "c" * 64, "u" * 64, None, _now() - timedelta(seconds=1))
        live = await repo.get_live_session("a" * 64)
        expired = await repo.get_live_session("c" * 64)
        await repo.revoke_session("a" * 64, "logout")
        after_logout = await repo.get_live_session("a" * 64)
        n = await repo.revoke_all_sessions(f.id, "logout_all")
        return live, expired, after_logout, n, await repo.get_live_session("b" * 64)

    live, expired, after_logout, n, b_after = run(body)
    session, farmer = live
    assert session.ip_address == "127.0.0.1" and farmer.email == "s@example.com"
    assert expired is None and after_logout is None
    assert n == 2 and b_after is None           # b plus the already-expired c


def test_token_single_use_even_when_used_concurrently():
    from app.database.repositories import auth_repository as repo

    async def body():
        f = await repo.create_farmer("t@example.com", "h", None, None)
        await repo.create_token(f.id, repo.PURPOSE_VERIFY_EMAIL, "v" * 64, _now() + timedelta(hours=1))
        results = await asyncio.gather(*(repo.verify_email_with_token("v" * 64) for _ in range(5)))
        return results, await repo.get_farmer_by_pk(f.id)

    results, farmer = run(body)
    assert sorted(r is not None for r in results) == [False, False, False, False, True]
    assert farmer.is_verified and farmer.email_verified_at is not None


def test_expired_and_superseded_tokens_rejected():
    from app.database.repositories import auth_repository as repo

    async def body():
        f = await repo.create_farmer("x@example.com", "h", None, None)
        await repo.create_token(f.id, repo.PURPOSE_RESET_PASSWORD, "1" * 64, _now() - timedelta(seconds=1))
        expired = await repo.reset_password_with_token("1" * 64, "new")
        await repo.create_token(f.id, repo.PURPOSE_RESET_PASSWORD, "2" * 64, _now() + timedelta(minutes=30))
        await repo.create_token(f.id, repo.PURPOSE_RESET_PASSWORD, "3" * 64, _now() + timedelta(minutes=30))
        superseded = await repo.reset_password_with_token("2" * 64, "new")
        wrong_purpose = await repo.verify_email_with_token("3" * 64)
        ok = await repo.reset_password_with_token("3" * 64, "new")
        return expired, superseded, wrong_purpose, ok

    expired, superseded, wrong_purpose, ok = run(body)
    assert expired is None and superseded is None and wrong_purpose is None and ok is not None


def test_password_reset_is_one_transaction_that_revokes_sessions():
    from app.database.repositories import auth_repository as repo

    async def body():
        f = await repo.create_farmer("r@example.com", "old-hash", None, None)
        await repo.record_login_failure(f.id, 2, 15)
        await repo.record_login_failure(f.id, 2, 15)                 # locks
        locked = (await repo.get_farmer_by_pk(f.id)).locked_until
        await repo.create_session(f.id, "d" * 64, "u" * 64, None, _now() + timedelta(hours=1))
        await repo.create_token(f.id, repo.PURPOSE_RESET_PASSWORD, "r" * 64, _now() + timedelta(minutes=30))
        pk = await repo.reset_password_with_token("r" * 64, "new-hash")
        return locked, pk, await repo.get_farmer_by_pk(f.id), await repo.get_live_session("d" * 64)

    locked, pk, farmer, session = run(body)
    assert locked is not None and locked > _now()
    assert pk == farmer.id and farmer.password_hash == "new-hash"
    assert farmer.locked_until is None and farmer.failed_login_count == 0 and farmer.is_verified
    assert farmer.password_changed_at is not None
    assert session is None


def test_change_password_revokes_all_sessions_and_login_success_stores_rehash():
    from app.database.repositories import auth_repository as repo

    async def body():
        f = await repo.create_farmer("c@example.com", "$2b$legacy", None, None)
        await repo.record_login_success(f.id, "$argon2id$upgraded")
        upgraded = (await repo.get_farmer_by_pk(f.id)).password_hash
        await repo.create_session(f.id, "e" * 64, "u" * 64, None, _now() + timedelta(hours=1))
        await repo.change_password(f.id, "$argon2id$changed")
        return upgraded, await repo.get_live_session("e" * 64), await repo.get_farmer_by_pk(f.id)

    upgraded, session, farmer = run(body)
    assert upgraded == "$argon2id$upgraded"
    assert session is None and farmer.password_hash == "$argon2id$changed"
