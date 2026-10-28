"""
Integration tests: migration 0004 and the real profile repository against PostgreSQL.

Opt-in, like test_auth_repository_pg.py (throw-away database; tables are truncated):
    TEST_DATABASE_URL=postgresql://schemesetu:schemesetu@localhost:5432/schemesetu_auth_test \
        python -m pytest app/tests/test_profile_repository_pg.py
"""

from __future__ import annotations

import asyncio

import pytest

from app.tests.test_auth_repository_pg import TEST_URL, _alembic, run

pytestmark = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL not set (PostgreSQL integration)")


@pytest.fixture(scope="module", autouse=True)
def migrated_db():
    _alembic("upgrade", "head")
    yield


async def _farmers(n=2):
    from app.database.repositories import auth_repository as auth
    return [await auth.create_farmer(f"p{i}@example.com", "h", None, None) for i in range(n)]


def test_migration_0004_converts_and_minimises_legacy_data():
    """Legacy row (exact income + Aadhaar status) → income range, cleared sensitive fields."""
    _alembic("downgrade", "0003")
    try:
        async def seed():
            from app.database.connection import get_db_connection
            (f,) = await _farmers(1)
            async with get_db_connection() as conn:
                await conn.execute(
                    "INSERT INTO farmer_profiles (farmer_id, state, land_size_acres, annual_income, "
                    "has_aadhaar, consent_given) VALUES (%s, 'Karnataka', 2.5, 180000, true, true)", (f.id,))
            return f.id
        pk = run(seed)
    finally:
        _alembic("upgrade", "head")

    async def read():
        from app.database.connection import get_db_connection
        async with get_db_connection() as conn:
            cur = await conn.execute(
                "SELECT land_size_value, land_unit, land_size_acres, income_range, annual_income, "
                "has_aadhaar, version FROM farmer_profiles WHERE farmer_id = %s", (pk,))
            return await cur.fetchone()

    # run() truncates first, so read through a fresh connection without truncating:
    from app.core.config import settings
    from app.database import connection

    async def read_only():
        old = settings.DATABASE_URL
        settings.DATABASE_URL = TEST_URL
        connection._pool = None
        await connection.init_db()
        try:
            return await read()
        finally:
            await connection.close_db()
            settings.DATABASE_URL = old

    connection.use_selector_event_loop_on_windows()
    value, unit, acres, income_range, income, aadhaar, version = asyncio.run(read_only())
    assert (float(value), unit, float(acres)) == (2.5, "acre", 2.5)
    assert income_range == "1_to_2.5_lakh"
    assert income is None and aadhaar is None                         # minimised
    assert version == 1


def test_save_insert_update_clear_and_version():
    from app.database.repositories import profile_repository as repo

    async def body():
        (f,) = await _farmers(1)
        r1 = await repo.save_profile(f.id, {"state": "Karnataka", "age": 40, "consent_given": True}, None)
        r2 = await repo.save_profile(f.id, {"age": None, "land_size_value": 0, "land_unit": "acre",
                                            "land_size_acres": 0}, r1.version)
        return r1, r2, await repo.get_profile(f.id)

    r1, r2, stored = run(body)
    assert r1.version == 1 and r2.version == 2
    assert stored.age is None and stored.state == "Karnataka"           # cleared to unknown, rest kept
    assert stored.land_size_acres == 0                                   # zero is a value


def test_stale_version_rejected_and_nothing_written():
    from app.database.repositories import profile_repository as repo

    async def body():
        (f,) = await _farmers(1)
        await repo.save_profile(f.id, {"district": "Mandya", "consent_given": True}, None)
        await repo.save_profile(f.id, {"district": "Hassan"}, 1)
        try:
            await repo.save_profile(f.id, {"district": "Tumkur"}, 1)
            conflict = False
        except repo.VersionConflict:
            conflict = True
        return conflict, await repo.get_profile(f.id)

    conflict, stored = run(body)
    assert conflict and stored.district == "Hassan" and stored.version == 2


def test_concurrent_saves_with_same_version_only_one_wins():
    from app.database.repositories import profile_repository as repo

    async def body():
        (f,) = await _farmers(1)
        await repo.save_profile(f.id, {"district": "Mandya", "consent_given": True}, None)

        async def attempt(d):
            try:
                await repo.save_profile(f.id, {"district": d}, 1)
                return d
            except repo.VersionConflict:
                return None

        winners = [w for w in await asyncio.gather(*(attempt(d) for d in ("A", "B", "C", "D"))) if w]
        return winners, await repo.get_profile(f.id)

    winners, stored = run(body)
    assert len(winners) == 1 and stored.district == winners[0] and stored.version == 2


def test_one_farmer_cannot_change_another_farmers_row():
    from app.database.repositories import profile_repository as repo

    async def body():
        a, b = await _farmers(2)
        await repo.save_profile(a.id, {"state": "Karnataka", "consent_given": True}, None)
        await repo.save_profile(b.id, {"state": "Punjab", "consent_given": True}, None)
        await repo.save_profile(b.id, {"state": "Haryana"}, None)
        return await repo.get_profile(a.id), await repo.get_profile(b.id)

    pa, pb = run(body)
    assert pa.state == "Karnataka" and pa.version == 1
    assert pb.state == "Haryana" and pb.version == 2


def test_database_constraints_reject_bad_values():
    from app.database.repositories import profile_repository as repo
    from app.core.exceptions import DatabaseError

    async def body():
        (f,) = await _farmers(1)
        results = {}
        for name, changes in {
            "bigha": {"land_size_value": 2, "land_unit": "bigha", "land_size_acres": 2},
            "unpaired": {"land_size_value": 2, "land_size_acres": 2},
            "range": {"income_range": "lots"},
            "residence": {"residence": "moon"},
        }.items():
            try:
                await repo.save_profile(f.id, {"consent_given": True, **changes}, None)
                results[name] = "accepted"
            except DatabaseError:
                results[name] = "rejected"
        with pytest.raises(ValueError):
            await repo.save_profile(f.id, {"has_aadhaar": True}, None)   # not a writable column
        return results, await repo.get_profile(f.id)

    results, stored = run(body)
    assert set(results.values()) == {"rejected"}
    assert stored is None
