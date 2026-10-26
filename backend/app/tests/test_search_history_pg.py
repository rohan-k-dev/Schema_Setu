"""
Integration tests: the real search-history repository against PostgreSQL —
retention (50 entries / 90 days), newest-first paging, and per-farmer deletion.

Opt-in, like test_auth_repository_pg.py (throw-away database; tables are truncated):
    TEST_DATABASE_URL=postgresql://schemesetu:schemesetu@localhost:5432/schemesetu_auth_test \
        python -m pytest app/tests/test_search_history_pg.py
"""

from __future__ import annotations

import pytest

from app.database.repositories import search_history_repository as hist
from app.tests.test_auth_repository_pg import TEST_URL, _alembic, run

pytestmark = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL not set (PostgreSQL integration)")


@pytest.fixture(scope="module", autouse=True)
def migrated_db():
    _alembic("upgrade", "head")
    yield


async def _farmers(n=2):
    from app.database.repositories import auth_repository as auth
    return [await auth.create_farmer(f"h{i}@example.com", "h", None, None) for i in range(n)]


async def _age(entry_query, days):
    from app.database.connection import get_db_connection
    async with get_db_connection() as conn:
        await conn.execute("UPDATE search_history SET searched_at = now() - make_interval(days => %s) "
                           "WHERE query = %s", (days, entry_query))
        await conn.commit()


def test_list_is_newest_first_and_paged():
    async def body():
        (f, _) = await _farmers()
        for q in ("first", "second", "third"):
            await hist.add(f.id, q, 2, "kn")
        page, total = await hist.list_page(f.id, 2, 1)
        return [r.query for r in page], total, page[0].language
    assert run(body) == (["second", "first"], 3, "kn")


def test_at_most_50_entries_are_kept():
    async def body():
        (f, _) = await _farmers()
        for i in range(hist.MAX_ENTRIES + 3):
            await hist.add(f.id, f"q{i}", 0, "en")
        rows, total = await hist.list_page(f.id, 50, 0)
        return total, rows[0].query, {r.query for r in rows}
    total, newest, kept = run(body)
    assert total == hist.MAX_ENTRIES and newest == f"q{hist.MAX_ENTRIES + 2}"
    assert {"q0", "q1", "q2"}.isdisjoint(kept)


def test_entries_older_than_90_days_are_removed():
    async def body():
        (f, _) = await _farmers()
        await hist.add(f.id, "old", 0, "en")
        await hist.add(f.id, "recent", 0, "en")
        await _age("old", hist.RETENTION_DAYS + 1)
        await _age("recent", hist.RETENTION_DAYS - 1)
        rows, total = await hist.list_page(f.id, 10, 0)
        from app.database.connection import get_db_connection
        async with get_db_connection() as conn:
            cur = await conn.execute("SELECT count(*) FROM search_history WHERE query = 'old'")
            stored = (await cur.fetchone())[0]
        return [r.query for r in rows], total, stored
    assert run(body) == (["recent"], 1, 0)                              # deleted, not just hidden


def test_delete_one_is_scoped_to_the_owner():
    async def body():
        a, b = await _farmers()
        await hist.add(a.id, "a-search", 0, "en")
        (a_row,), _ = await hist.list_page(a.id, 1, 0)
        by_other = await hist.delete_one(b.id, a_row.id)
        still_there = (await hist.list_page(a.id, 10, 0))[1]
        by_owner = await hist.delete_one(a.id, a_row.id)
        again = await hist.delete_one(a.id, a_row.id)
        return by_other, still_there, by_owner, again, (await hist.list_page(a.id, 10, 0))[1]
    assert run(body) == (False, 1, True, False, 0)


def test_clear_removes_only_own_history():
    async def body():
        a, b = await _farmers()
        for q in ("a1", "a2"):
            await hist.add(a.id, q, 0, "en")
        await hist.add(b.id, "b1", 0, "en")
        deleted = await hist.clear(a.id)
        return deleted, (await hist.list_page(a.id, 10, 0))[1], (await hist.list_page(b.id, 10, 0))[1]
    assert run(body) == (2, 0, 1)


def test_history_is_deleted_with_the_account():
    async def body():
        from app.database.connection import get_db_connection
        (f, _) = await _farmers()
        await hist.add(f.id, "q", 0, "en")
        async with get_db_connection() as conn:
            await conn.execute("DELETE FROM farmers WHERE id = %s", (f.id,))
            await conn.commit()
            cur = await conn.execute("SELECT count(*) FROM search_history")
            return (await cur.fetchone())[0]
    assert run(body) == 0
