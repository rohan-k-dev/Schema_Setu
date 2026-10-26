"""
Integration tests: the persistent review queue against PostgreSQL (migration 0009,
docs/HUMAN_REVIEW.md) — constraints, the full workflow through the real repository with
history and hash-chained audit events in the same transaction, simultaneous claims and
escalations on separate connections, the append-only history, and the farmer link.

Opt-in, like test_auth_repository_pg.py (throw-away database; tables are truncated):
    TEST_DATABASE_URL=postgresql://schemesetu:schemesetu@localhost:5432/schemesetu_auth_test \
        python -m pytest app/tests/test_review_pg.py
"""

from __future__ import annotations

import asyncio

import pytest

from app.core.permissions import Principal, permissions_for
from app.models.review import ReviewAction
from app.tests.test_auth_repository_pg import TEST_URL, _alembic
from app.tests.test_rbac_pg import run as _run

pytestmark = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL not set (PostgreSQL integration)")


@pytest.fixture(scope="module", autouse=True)
def migrated_db():
    _alembic("upgrade", "head")
    yield


def run(factory):
    async def body():
        from app.database.connection import get_db_connection
        async with get_db_connection() as conn:
            await conn.execute("TRUNCATE review_cases CASCADE")
        return await factory()
    return _run(body)


def rev(i=1):
    return Principal(role=None, label=f"rev{i}@example.com", account_pk=None,
                     permissions=permissions_for("REVIEWER"))


async def _case(session="s1"):
    from app.tests.test_review_workflow import escalate
    return await escalate(session=session)


async def _scalar(q, params=()):
    from app.database.connection import get_db_connection
    async with get_db_connection() as conn:
        return (await (await conn.execute(q, params)).fetchone())[0]


def test_migration_is_reversible_and_constraints_hold():
    _alembic("downgrade", "0008")
    _alembic("upgrade", "head")

    async def body():
        from psycopg import errors
        from app.database.connection import get_db_connection
        bad = []
        for sql in ("INSERT INTO review_cases (case_id, session_id, reason, status) VALUES ('a', 's', 'NOPE', 'PENDING')",
                    "INSERT INTO review_cases (case_id, session_id, reason, status) VALUES ('b', 's', 'OTHER', 'RESOLVED')",
                    "INSERT INTO review_cases (case_id, session_id, reason, status) VALUES ('c', 's', 'OTHER', 'IN_REVIEW')",
                    "INSERT INTO review_cases (case_id, session_id, reason, status, decision) "
                    "VALUES ('d', 's', 'OTHER', 'PENDING', 'APPROVE')"):
            try:
                async with get_db_connection() as conn:
                    await conn.execute(sql)
                    await conn.commit()
            except Exception as exc:
                cause = exc.__cause__ or exc
                bad.append(isinstance(cause, errors.CheckViolation) or "check constraint" in str(cause))
        return bad, await _scalar("SELECT count(*) FROM review_cases")
    assert run(body) == ([True, True, True, True], 0)


def test_full_workflow_writes_history_and_a_valid_audit_chain():
    async def body():
        from app.database.repositories import audit_repository
        from app.services import review_workflow as wf
        c = await _case()
        assert c["status"] == "PENDING" and c["version"] == 1 and c["schemes"][0]["name"] == "Conflicted Scheme"
        c = await wf.claim(rev(), c["case_id"], 1)
        await wf.comment(rev(), c["case_id"], "checking the gazette")
        c = await wf.act(rev(), c["case_id"], ReviewAction.REQUEST_INFORMATION, "asked the office", c["version"])
        c = await wf.act(rev(), c["case_id"], ReviewAction.REJECT, "typo in the source", c["version"],
                         data_correction_needed=True)
        events = [e["event"] for e in (await wf.get_case(rev(), c["case_id"]))["history"]]
        actions = await _scalar("SELECT array_agg(action ORDER BY id) FROM audit_events WHERE target_id = %s",
                                (c["case_id"],))
        return c, events, actions, await audit_repository.verify_chain()
    c, events, actions, chain = run(body)
    assert (c["status"], c["decision"], c["data_correction_needed"], c["version"]) == ("RESOLVED", "REJECT", True, 4)
    assert events == ["CREATED", "ASSIGNED", "COMMENT", "VERIFICATION_REQUESTED", "REJECT"]
    assert actions == ["REVIEW_CASE_CREATED", "REVIEW_ASSIGNED", "REVIEW_COMMENTED", "REVIEW_REQUEST_INFORMATION",
                       "REVIEW_REJECT", "REVIEW_CASE_VIEWED"]
    assert chain["valid"]


def test_simultaneous_claims_on_separate_connections_only_one_wins():
    async def body():
        from app.services import review_workflow as wf
        c = await _case()
        results = await asyncio.gather(*(wf.claim(rev(i), c["case_id"], 1) for i in range(6)),
                                       return_exceptions=True)
        assigned = await _scalar("SELECT count(*) FROM review_case_events WHERE case_id = %s AND event = 'ASSIGNED'",
                                 (c["case_id"],))
        return results, assigned, await _scalar("SELECT version FROM review_cases WHERE case_id = %s", (c["case_id"],))
    results, assigned, version = run(body)
    assert sum(isinstance(r, dict) for r in results) == 1 and assigned == 1 and version == 2
    assert all(getattr(r, "status", None) == 409 for r in results if not isinstance(r, dict))


def test_simultaneous_escalations_open_one_case():
    async def body():
        cases = await asyncio.gather(*(_case("same") for _ in range(6)))
        return {c["case_id"] for c in cases}, await _scalar("SELECT count(*) FROM review_cases")
    ids, count = run(body)
    assert len(ids) == 1 and count == 1


def test_history_is_append_only():
    async def body():
        from app.database.connection import get_db_connection
        c = await _case()
        refused = []
        for sql in ("UPDATE review_case_events SET note = 'x'", "DELETE FROM review_case_events"):
            try:
                async with get_db_connection() as conn:
                    await conn.execute(sql)
                    await conn.commit()
                refused.append(False)
            except Exception as exc:
                refused.append("append-only" in str(exc))
        return refused, await _scalar("SELECT count(*) FROM review_case_events WHERE case_id = %s", (c["case_id"],))
    refused, count = run(body)
    assert refused == [True, True] and count == 1


def test_farmer_link_listing_and_account_deletion():
    async def body():
        from app.database.connection import get_db_connection
        from app.database.repositories import auth_repository as auth
        from app.services import review_workflow as wf
        f = await auth.create_farmer("farmer@example.com", "h", None, None)
        c = await _case()
        await wf.link_farmer(c["case_id"], f.id)
        mine = await wf.cases_for_farmer(f.id)
        open_ids = await wf.open_scheme_ids_for_farmer(f.id)
        async with get_db_connection() as conn:
            await conn.execute("DELETE FROM farmers WHERE id = %s", (f.id,))
            await conn.commit()
        kept = await _scalar("SELECT farmer_id IS NULL FROM review_cases WHERE case_id = %s", (c["case_id"],))
        return mine, open_ids, kept
    mine, open_ids, kept = run(body)
    assert len(mine) == 1 and mine[0]["open"] and open_ids == {"CONFLICTED"}
    assert kept is True                                  # the case stays (for the record), unlinked


def test_list_filters_and_stats_in_sql():
    async def body():
        from app.services import review_workflow as wf
        a = await _case("s1")
        b = await _case("s2")
        await wf.claim(rev(1), b["case_id"])
        pending = await wf.list_cases(rev(1), "PENDING")
        mine = await wf.list_cases(rev(1), None, None, "me")
        unassigned = await wf.list_cases(rev(1), None, None, "unassigned")
        return a["case_id"], b["case_id"], pending, mine, unassigned
    a, b, pending, mine, unassigned = run(body)
    assert [c["case_id"] for c in pending["cases"]] == [a]
    assert [c["case_id"] for c in mine["cases"]] == [b]
    assert [c["case_id"] for c in unassigned["cases"]] == [a]
    assert pending["stats"]["pending"] == 1 and pending["stats"]["in_review"] == 1
