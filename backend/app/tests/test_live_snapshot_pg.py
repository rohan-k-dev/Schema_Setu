"""
Integration tests: provenance snapshots of live official sources against PostgreSQL
(migration 0011, docs/LIVE_VERIFICATION.md).

A valid record is never overwritten by a worse one: the last known-good extraction survives
partial, unparseable, missing and failed fetches; an update keeps the previous good version;
the same content under another URL is flagged as a duplicate; the admin listing filters by change.

Opt-in, like test_auth_repository_pg.py (throw-away database; the table is truncated):
    TEST_DATABASE_URL=postgresql://schemesetu:schemesetu@localhost:5432/schemesetu_auth_test \
        python -m pytest app/tests/test_live_snapshot_pg.py
"""

from __future__ import annotations

import pytest

from app.tests.test_auth_repository_pg import TEST_URL, _alembic
from app.tests.test_rbac_pg import run as _run

pytestmark = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL not set (PostgreSQL integration)")

URL = "https://pmkisan.gov.in/"
FULL = {"eligibility": {"value": ["Landholding farmer families"], "evidence": "x"},
        "benefit_amounts": {"value": [{"amount": 6000, "per": "year"}], "evidence": "Rs. 6,000 per year"},
        "documents": {"value": ["Aadhaar"], "evidence": "Aadhaar"}}


@pytest.fixture(scope="module", autouse=True)
def migrated_db():
    _alembic("upgrade", "head")
    yield


def run(factory):
    async def body():
        from app.database.connection import get_db_connection
        async with get_db_connection() as conn:
            await conn.execute("TRUNCATE live_source_snapshots")
        return await factory()
    return _run(body)


async def rec(url=URL, *, ok=True, not_found=False, quality="COMPLETE", fields=None, h="h1", status="OK"):
    from app.database.repositories import live_snapshot_repository as repo
    return await repo.record(canonical=url, url=url, host="pmkisan.gov.in", category="MINISTRY", scheme_id="PM_KISAN",
                             method="direct", status=status, http_status=200 if ok else None, ok=ok,
                             not_found=not_found, quality=quality, fields=FULL if fields is None else fields,
                             content_hash=h if ok else "", etag=None, last_modified=None,
                             error=None if ok else "unreachable")


def test_new_unchanged_and_updated_keep_the_previous_good_version():
    async def body():
        first = await rec()
        assert first["change_status"] == "NEW" and first["last_good"] == FULL and first["first_seen_at"]
        same = await rec()
        assert same["change_status"] == "UNCHANGED" and same["previous_good"] is None
        richer = {**FULL, "ministry": {"value": "Ministry of Agriculture", "evidence": "m"}}
        upd = await rec(fields=richer, h="h2")
        assert upd["change_status"] == "UPDATED" and upd["last_good"] == richer
        assert upd["previous_good"] == FULL and upd["previous_good_at"] == same["last_good_at"]
    run(body)


def test_worse_results_never_overwrite_the_last_known_good():
    async def body():
        good = await rec()
        partial = await rec(quality="PARTIAL", fields={"eligibility": FULL["eligibility"]}, h="h3")
        assert partial["change_status"] == "INCOMPLETE" and partial["last_good"] == FULL
        assert partial["attempt_extracted"] == {"eligibility": FULL["eligibility"]}
        empty = await rec(quality="EMPTY", fields={}, h="h4")
        assert empty["change_status"] == "UNPARSEABLE" and empty["last_good"] == FULL
        gone = await rec(ok=False, not_found=True, quality="EMPTY", fields={}, status="NOT_FOUND")
        assert gone["change_status"] == "MISSING" and gone["last_good"] == FULL
        down = await rec(ok=False, quality="EMPTY", fields={}, status="TIMEOUT")
        assert down["change_status"] == "FAILED" and down["last_good"] == FULL and down["error"]
        assert down["last_success_at"] == empty["last_success_at"] and down["last_good_at"] == good["last_good_at"]
    run(body)


def test_same_content_under_another_url_is_a_duplicate_and_listing_filters():
    async def body():
        from app.database.repositories import live_snapshot_repository as repo
        await rec()
        dup = await rec("https://www.pmkisan.gov.in/home")
        assert dup["duplicate_of"] == URL
        await rec(quality="PARTIAL", fields={"eligibility": FULL["eligibility"]}, h="h9")
        rows, total = await repo.list_recent("INCOMPLETE", 10, 0)
        assert total == 1 and rows[0]["canonical_url"] == URL
        rows, total = await repo.list_recent(None, 10, 0)
        assert total == 2
    run(body)
