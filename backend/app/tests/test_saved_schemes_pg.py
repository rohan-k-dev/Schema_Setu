"""
Integration tests: saved schemes + application checklists against PostgreSQL —
migration 0005, the real repository SQL through the service, duplicate and concurrent
saves, progress persistence, scheme updates (including a re-import that only changes
database ids), ownership enforced by the queries AND by the composite foreign key.

Opt-in, like test_auth_repository_pg.py (throw-away database; farmers and schemes are truncated):
    TEST_DATABASE_URL=postgresql://schemesetu:schemesetu@localhost:5432/schemesetu_auth_test \
        python -m pytest app/tests/test_saved_schemes_pg.py
"""

from __future__ import annotations

import asyncio

import pytest

from app.models.auth_schemas import SaveSchemeRequest
from app.models.saved_scheme_schemas import (
    ChecklistItemUpdateRequest,
    MilestoneCreateRequest,
    SavedSchemeUpdateRequest,
)
from app.tests.test_auth_repository_pg import TEST_URL, _alembic

pytestmark = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL not set (PostgreSQL integration)")


@pytest.fixture(scope="module", autouse=True)
def migrated_db():
    _alembic("upgrade", "head")
    _alembic("downgrade", "0004")        # migration 0005 is reversible
    _alembic("upgrade", "head")
    yield


def run(coro_factory, truncate: bool = True):
    """Run one async test body with a fresh pool on the test database."""
    from app.core.config import settings
    from app.database import connection

    async def body():
        old = settings.DATABASE_URL
        settings.DATABASE_URL = TEST_URL
        connection._pool = None
        await connection.init_db()
        try:
            if truncate:
                async with connection.get_db_connection() as conn:
                    await conn.execute("TRUNCATE farmers, schemes RESTART IDENTITY CASCADE")
            return await coro_factory()
        finally:
            await connection.close_db()
            settings.DATABASE_URL = old

    connection.use_selector_event_loop_on_windows()
    return asyncio.run(body())


DOCS = [("Aadhaar Card", True), ("Land Records", True)]
STEPS = [(1, "Visit the portal or nearest CSC", "HYBRID"), (2, "Register with bank details", "ONLINE")]


async def _put_scheme(sid="PM_TEST", docs=DOCS, steps=STEPS, status="ACTIVE", data_version="1.0"):
    """Insert or re-import a scheme the way corpus_import_service does (children deleted + re-inserted)."""
    from app.database.connection import get_db_connection
    async with get_db_connection() as conn:
        cur = await conn.execute("SELECT id FROM schemes WHERE scheme_id = %s", (sid,))
        row = await cur.fetchone()
        if row:
            pk = row[0]
            await conn.execute("UPDATE schemes SET status = %s, data_version = %s, updated_at = NOW() "
                               "WHERE id = %s", (status, data_version, pk))
            await conn.execute("DELETE FROM scheme_documents WHERE scheme_id = %s", (pk,))
            await conn.execute("DELETE FROM application_steps WHERE scheme_id = %s", (pk,))
        else:
            cur = await conn.execute(
                "INSERT INTO schemes (scheme_id, name, description, status, data_version, official_url) "
                "VALUES (%s, %s, 'test', %s, %s, 'https://example.gov.in') RETURNING id",
                (sid, f"Scheme {sid}", status, data_version))
            pk = (await cur.fetchone())[0]
        for i, (name, mandatory) in enumerate(docs):
            await conn.execute("INSERT INTO scheme_documents (scheme_id, name, mandatory, document_order) "
                               "VALUES (%s, %s, %s, %s)", (pk, name, mandatory, i))
        for n, desc, mode in steps:
            await conn.execute("INSERT INTO application_steps (scheme_id, step_number, description, mode) "
                               "VALUES (%s, %s, %s, %s)", (pk, n, desc, mode))
        await conn.commit()


async def _farmers(n=2):
    from app.database.repositories import auth_repository as auth
    return [await auth.create_farmer(f"s{i}@example.com", "h", None, None) for i in range(n)]


def _svc():
    from app.services import saved_scheme_service
    return saved_scheme_service


def test_migration_created_table_and_constraints():
    async def body():
        from app.database.connection import get_db_connection
        async with get_db_connection() as conn:
            cur = await conn.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'saved_schemes'")
            cols = {r[0] for r in await cur.fetchall()}
            cur = await conn.execute(
                "SELECT conname FROM pg_constraint WHERE conrelid = 'saved_scheme_checklist_items'::regclass")
            cons = {r[0] for r in await cur.fetchall()}
        return cols, cons
    cols, cons = run(body)
    assert {"scheme_version", "saved_scheme_version", "application_reference", "scheme_update_seen"} <= cols
    assert {"fk_checklist_saved_scheme_owner", "uq_checklist_item_key", "ck_checklist_source"} <= cons


def test_save_builds_versioned_checklist_and_duplicate_save_changes_nothing():
    async def body():
        svc = _svc()
        (a, _) = await _farmers()
        await _put_scheme()
        first = await svc.save_scheme(a.farmer_id, SaveSchemeRequest(scheme_id="PM_TEST", scheme_name="Fake",
                                                                     notes="ask at bank"))
        again = await svc.save_scheme(a.farmer_id, SaveSchemeRequest(scheme_id="PM_TEST", notes="other"))
        listed = await svc.list_saved_schemes(a.farmer_id)
        return first, again, listed
    first, again, listed = run(body)
    assert first.created is True and again.created is False
    assert first.scheme_name == "Scheme PM_TEST"                      # from the database, not the client
    assert [i.category for i in first.checklist] == [
        "DOCUMENT", "DOCUMENT", "PREPARATION", "PREPARATION", "APPLICATION", "APPLICATION",
        "SUBMISSION", "ACKNOWLEDGEMENT"]
    assert first.scheme_version and first.scheme_version == first.saved_scheme_version
    assert again.notes == "ask at bank" and len(again.checklist) == 8
    assert len(listed) == 1 and listed[0].progress.total == 8
    assert listed[0].progress_source == "USER_REPORTED" and listed[0].official_tracking is False


def test_concurrent_saves_create_one_row_and_one_checklist():
    async def body():
        svc = _svc()
        (a, _) = await _farmers()
        await _put_scheme()
        results = await asyncio.gather(*[svc.save_scheme(a.farmer_id, SaveSchemeRequest(scheme_id="PM_TEST"))
                                         for _ in range(4)])
        from app.database.connection import get_db_connection
        async with get_db_connection() as conn:
            saved = (await (await conn.execute("SELECT count(*) FROM saved_schemes")).fetchone())[0]
            items = (await (await conn.execute("SELECT count(*) FROM saved_scheme_checklist_items")).fetchone())[0]
        return [r.created for r in results], saved, items
    created, saved, items = run(body)
    assert sorted(created) == [False, False, False, True]
    assert (saved, items) == (1, 8)


def test_progress_notes_and_reference_persist():
    async def body():
        svc = _svc()
        (a, _) = await _farmers()
        await _put_scheme()
        d = await svc.save_scheme(a.farmer_id, SaveSchemeRequest(scheme_id="PM_TEST"))
        doc, submit = d.checklist[0], next(i for i in d.checklist if i.key == "submit:application")
        await svc.update_item(a.farmer_id, "PM_TEST", doc.id,
                              ChecklistItemUpdateRequest(completed=True, note="original + 2 copies"))
        await svc.update_item(a.farmer_id, "PM_TEST", submit.id, ChecklistItemUpdateRequest(completed=True))
        await svc.update_saved_scheme(a.farmer_id, "PM_TEST",
                                      SavedSchemeUpdateRequest(application_reference="KA/2026/123"))
        await svc.add_milestone(a.farmer_id, "PM_TEST", MilestoneCreateRequest(label="Field visit done"))
        return d.checklist[0].id
    doc_id = run(body)

    async def reread():                                   # a fresh pool: what is stored, not cached
        return await _svc().get_saved_scheme((await _farmer_by_email("s0@example.com")).farmer_id, "PM_TEST")
    d = run(reread, truncate=False)
    doc = next(i for i in d.checklist if i.id == doc_id)
    assert doc.completed and doc.completed_at and doc.note == "original + 2 copies"
    assert d.application_reference == "KA/2026/123" and d.progress.stage == "SUBMITTED"
    assert d.checklist[-1].source == "USER" and d.checklist[-1].category == "MILESTONE"
    assert (d.progress.completed, d.progress.total) == (2, 9)

    async def reopen():
        svc = _svc()
        f = await _farmer_by_email("s0@example.com")
        return await svc.update_item(f.farmer_id, "PM_TEST", doc_id, ChecklistItemUpdateRequest(completed=False))
    d = run(reopen, truncate=False)
    doc = next(i for i in d.checklist if i.id == doc_id)
    assert doc.completed is False and doc.completed_at is None and doc.note == "original + 2 copies"


async def _farmer_by_email(email):
    from app.database.repositories import auth_repository as auth
    return await auth.get_farmer_by_email(email)


def test_scheme_update_keeps_progress_adds_and_retires_items():
    async def body():
        svc = _svc()
        (a, _) = await _farmers()
        await _put_scheme()
        d = await svc.save_scheme(a.farmer_id, SaveSchemeRequest(scheme_id="PM_TEST"))
        aadhaar = next(i for i in d.checklist if i.label == "Aadhaar Card")
        land = next(i for i in d.checklist if i.label == "Land Records")
        await svc.update_item(a.farmer_id, "PM_TEST", aadhaar.id, ChecklistItemUpdateRequest(completed=True))
        await svc.update_item(a.farmer_id, "PM_TEST", land.id, ChecklistItemUpdateRequest(completed=True))

        await _put_scheme()                                # re-import, same content, new child ids
        same = await svc.get_saved_scheme(a.farmer_id, "PM_TEST")

        await _put_scheme(docs=[("Aadhaar Card", True), ("Bank Passbook", True)], data_version="1.1")
        updated = await svc.get_saved_scheme(a.farmer_id, "PM_TEST")
        acked = await svc.update_saved_scheme(a.farmer_id, "PM_TEST",
                                              SavedSchemeUpdateRequest(acknowledge_scheme_update=True))
        return d, same, updated, acked, aadhaar.id, land.id
    d, same, updated, acked, aadhaar_id, land_id = run(body)
    assert same.scheme_version == d.scheme_version and same.update_notice is None
    assert updated.scheme_version != d.scheme_version and updated.saved_scheme_version == d.scheme_version
    assert updated.scheme_data_version == "1.1"
    by_id = {i.id: i for i in updated.checklist}
    assert by_id[aadhaar_id].completed and by_id[aadhaar_id].current            # progress kept
    assert by_id[land_id].completed and not by_id[land_id].current               # kept, no longer listed
    bank = next(i for i in updated.checklist if i.label == "Bank Passbook")
    assert bank.added_in_update and not bank.completed
    assert updated.update_notice.added == ["Bank Passbook"]
    assert updated.update_notice.removed == ["Land Records"]
    assert (updated.progress.completed, updated.progress.total) == (1, 8)        # retired item not counted
    assert acked.update_notice is None and len(acked.checklist) == 9


def test_other_farmer_cannot_touch_items_even_with_the_same_scheme_saved():
    async def body():
        from app.database.repositories import saved_scheme_repository as repo
        svc = _svc()
        a, b = await _farmers()
        await _put_scheme()
        da = await svc.save_scheme(a.farmer_id, SaveSchemeRequest(scheme_id="PM_TEST"))
        await svc.save_scheme(b.farmer_id, SaveSchemeRequest(scheme_id="PM_TEST"))
        da = await svc.add_milestone(a.farmer_id, "PM_TEST", MilestoneCreateRequest(label="mine"))
        item, mine = da.checklist[0], da.checklist[-1]
        upd = await repo.update_item(b.id, "PM_TEST", item.id, {"completed": True})
        dele = await repo.delete_milestone(b.id, "PM_TEST", mine.id)
        peek = await repo.list_items(b.id, [da.id])
        ref = await repo.update_saved(b.id, "PM_TEST", {"application_reference": "X1"})
        after = await svc.get_saved_scheme(a.farmer_id, "PM_TEST")
        return upd, dele, peek, ref.id != da.id, after
    upd, dele, peek, other_row, after = run(body)
    assert upd is None and dele is False and peek == [] and other_row
    assert not any(i.completed for i in after.checklist) and after.checklist[-1].label == "mine"
    assert after.application_reference is None


def test_database_rejects_item_owned_by_a_different_farmer():
    async def body():
        from psycopg import errors
        from app.database.connection import get_db_connection
        svc = _svc()
        a, b = await _farmers()
        await _put_scheme()
        da = await svc.save_scheme(a.farmer_id, SaveSchemeRequest(scheme_id="PM_TEST"))
        async with get_db_connection() as conn:
            try:
                await conn.execute(
                    "INSERT INTO saved_scheme_checklist_items (saved_scheme_id, farmer_id, item_key, category, "
                    "source, label) VALUES (%s, %s, 'user:x', 'MILESTONE', 'USER', 'sneaky')", (da.id, b.id))
            except errors.ForeignKeyViolation:
                return "rejected"
        return "accepted"
    assert run(body) == "rejected"


def test_unsave_and_account_deletion_remove_checklists():
    async def body():
        from app.database.connection import get_db_connection
        svc = _svc()
        a, b = await _farmers()
        await _put_scheme()
        await _put_scheme("PM_OTHER")
        for f in (a, b):
            await svc.save_scheme(f.farmer_id, SaveSchemeRequest(scheme_id="PM_TEST"))
        await svc.save_scheme(a.farmer_id, SaveSchemeRequest(scheme_id="PM_OTHER"))
        removed = await svc.unsave_scheme(a.farmer_id, "PM_TEST")
        again = await svc.unsave_scheme(a.farmer_id, "PM_TEST")
        async with get_db_connection() as conn:
            counts = [(await (await conn.execute(q)).fetchone())[0] for q in (
                "SELECT count(*) FROM saved_scheme_checklist_items",)]
            await conn.execute("DELETE FROM farmers WHERE id = %s", (a.id,))
            await conn.commit()
            counts.append((await (await conn.execute(
                "SELECT count(*) FROM saved_scheme_checklist_items")).fetchone())[0])
        return removed, again, counts, [s.scheme_id for s in await svc.list_saved_schemes(b.farmer_id)]
    removed, again, counts, b_left = run(body)
    assert removed is True and again is False
    assert counts == [16, 8]                  # A's PM_OTHER + B's PM_TEST, then only B's
    assert b_left == ["PM_TEST"]


def test_milestone_limit_and_constraints():
    async def body():
        from psycopg import errors
        from app.database.connection import get_db_connection
        from app.database.repositories import saved_scheme_repository as repo
        svc = _svc()
        (a, _) = await _farmers()
        await _put_scheme()
        d = await svc.save_scheme(a.farmer_id, SaveSchemeRequest(scheme_id="PM_TEST"))
        for i in range(repo.MAX_USER_MILESTONES):
            await repo.add_milestone(a.id, "PM_TEST", f"user:{i}", f"m{i}", None, False)
        try:
            await repo.add_milestone(a.id, "PM_TEST", "user:x", "one too many", None, False)
            limit = False
        except repo.MilestoneLimit:
            limit = True
        violations = []
        for q, params in (
            ("UPDATE saved_scheme_checklist_items SET note = %s WHERE id = %s", ("x" * 501, d.checklist[0].id)),
            ("UPDATE saved_scheme_checklist_items SET category = 'MILESTONE' WHERE id = %s", (d.checklist[0].id,)),
            ("UPDATE saved_scheme_checklist_items SET completed_at = NOW() WHERE id = %s", (d.checklist[0].id,)),
        ):
            async with get_db_connection() as conn:
                try:
                    await conn.execute(q, params)
                except errors.CheckViolation:
                    violations.append(True)
        return limit, violations
    limit, violations = run(body)
    assert limit is True and violations == [True, True, True]


def test_scheme_saved_before_migration_gets_its_checklist_on_first_read():
    _alembic("downgrade", "0004")

    async def legacy():
        (a,) = await _farmers(1)
        await _put_scheme()
        from app.database.connection import get_db_connection
        async with get_db_connection() as conn:
            await conn.execute("INSERT INTO saved_schemes (farmer_id, scheme_id, scheme_name, notes) "
                               "VALUES (%s, 'PM_TEST', 'Old name', 'kept')", (a.id,))
            await conn.commit()
        return a.farmer_id
    try:
        farmer_id = run(legacy)
    finally:
        _alembic("upgrade", "head")

    async def first_read():
        return await _svc().get_saved_scheme(farmer_id, "PM_TEST")
    d = run(first_read, truncate=False)
    assert d.notes == "kept" and d.scheme_name == "Scheme PM_TEST" and len(d.checklist) == 8
    assert d.update_notice is None and d.saved_scheme_version == d.scheme_version
