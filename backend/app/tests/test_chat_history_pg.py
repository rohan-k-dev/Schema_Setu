"""
Integration tests: saved conversations against PostgreSQL (migration 0012, docs/CHAT_HISTORY.md).

Turns are appended to the owner's conversation only; listing / opening / deleting is scoped to the account;
caps on conversations and messages; the setting; account deletion cascades; the retention purge.

Opt-in, like test_auth_repository_pg.py (throw-away database; tables are truncated):
    TEST_DATABASE_URL=postgresql://schemesetu:schemesetu@localhost:5432/schemesetu_auth_test \
        python -m pytest app/tests/test_chat_history_pg.py
"""

from __future__ import annotations

import uuid

import pytest

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
            await conn.execute("TRUNCATE sessions CASCADE")
        return await factory()
    return _run(body)


async def farmer(tag):
    from app.database.repositories import auth_repository as auth
    f = await auth.create_farmer(f"{tag}-{uuid.uuid4().hex[:6]}@example.com", "h", "Name", None)
    return f.id


async def turn(pk, thread, q="question", a="answer", **kw):
    from app.database.repositories import chat_history_repository as repo
    await repo.record_turn(pk, thread, q, a, language=kw.get("language", "en"), input_mode=kw.get("mode", "text"),
                           status=kw.get("status", "schemes_found"), schemes=kw.get("schemes"))


def test_turns_are_appended_listed_and_opened():
    async def body():
        from app.database.repositories import chat_history_repository as repo
        pk = await farmer("a")
        await turn(pk, "t1", "मैं बिहार का किसान हूँ", "जवाब", language="hi", mode="voice",
                   schemes=[{"scheme_id": "PM_KISAN", "name": "PM-KISAN"}])
        await turn(pk, "t1", "second", "answer 2")
        await turn(pk, "t2", "other chat", "answer")
        rows, total = await repo.list_page(pk, 10, 0)
        assert total == 2 and rows[0]["thread_id"] == "t2"                   # most recent first
        conv = await repo.get(pk, "t1")
        assert conv["title"] == "मैं बिहार का किसान हूँ" and conv["message_count"] == 4 and conv["language"] == "en"
        assert [m["role"] for m in conv["messages"]] == ["USER", "ASSISTANT", "USER", "ASSISTANT"]
        first_reply = conv["messages"][1]
        assert first_reply["language"] == "hi" and first_reply["input_mode"] == "voice"
        assert first_reply["schemes"] == [{"scheme_id": "PM_KISAN", "name": "PM-KISAN"}]
        assert [m["content"] for m in (await repo.get(pk, "t1", last=2))["messages"]] == ["second", "answer 2"]
        assert await repo.owner("t1") == (True, pk) and await repo.owner("nope") == (False, None)
    run(body)


def test_other_accounts_cannot_append_read_or_delete():
    async def body():
        from app.database.repositories import chat_history_repository as repo
        a, b = await farmer("a"), await farmer("b")
        await turn(a, "ta", "private", "answer")
        with pytest.raises(repo.NotYours):
            await turn(b, "ta", "intrusion", "x")
        assert await repo.get(b, "ta") is None and await repo.delete_one(b, "ta") is False
        assert (await repo.list_page(b, 10, 0)) == ([], 0)
        assert (await repo.get(a, "ta"))["message_count"] == 2
        assert await repo.clear(b) == [] and (await repo.get(a, "ta")) is not None
    run(body)


def test_caps_settings_and_delete():
    async def body():
        from app.database.repositories import chat_history_repository as repo
        pk = await farmer("c")
        old = (repo.MAX_MESSAGES, repo.MAX_CONVERSATIONS)
        repo.MAX_MESSAGES, repo.MAX_CONVERSATIONS = 4, 2
        try:
            for i in range(3):
                await turn(pk, "tc", f"q{i}", f"a{i}")
            conv = await repo.get(pk, "tc")
            assert conv["message_count"] == 4 and conv["messages"][0]["content"] == "q1"   # oldest dropped
            await turn(pk, "td", "d", "d")
            await turn(pk, "te", "e", "e")
            assert sorted(r["thread_id"] for r in (await repo.list_page(pk, 10, 0))[0]) == ["td", "te"]
        finally:
            repo.MAX_MESSAGES, repo.MAX_CONVERSATIONS = old
        assert await repo.is_enabled(pk) is True
        await repo.set_enabled(pk, False)
        assert await repo.is_enabled(pk) is False
        assert await repo.delete_one(pk, "td") is True and sorted(await repo.clear(pk)) == ["te"]
    run(body)


def test_account_deletion_cascades_and_retention_purge():
    async def body():
        from app.database.connection import get_db_connection
        from app.database.repositories import chat_history_repository as repo
        from app.database.repositories import privacy_repository
        from app.core.permissions import Principal, Role, permissions_for
        pk, other = await farmer("d"), await farmer("e")
        await turn(pk, "tdel", "q", "a")
        await turn(other, "tkeep", "q", "a")
        await turn(other, "told", "q", "a")
        actor = Principal(role=Role.FARMER, label="x", account_pk=pk, farmer_id="x", permissions=permissions_for(Role.FARMER))
        result = await privacy_repository.delete_account(pk, actor)
        assert result["counts"]["chat_conversations"] == 1 and "tdel" in result["chat_threads"]
        assert await repo.owner("tdel") == (False, None) and (await repo.owner("tkeep"))[0]
        async with get_db_connection() as conn:
            await conn.execute("UPDATE sessions SET last_activity_at = now() - interval '400 days' "
                               "WHERE thread_id = 'told'")
            await conn.commit()
        out = await privacy_repository.purge_expired(30, 7, 365, 365, 90, 365)
        assert out["chat_history"] == 1 and await repo.owner("told") == (False, None)
        assert (await repo.owner("tkeep"))[0]
    run(body)
