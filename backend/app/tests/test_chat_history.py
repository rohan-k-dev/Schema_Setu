"""
Chat history per account (docs/CHAT_HISTORY.md): every signed-in chat / voice turn is saved; the farmer can
list, open, continue and delete their conversations, or turn saving off. Another account's conversation can't
be read, deleted or continued (not even by sending its thread id to /chat). Anonymous chats are not stored.

HTTP API with real sessions (the RBAC environment) and an in-memory stand-in for the chat-history tables;
the SQL itself is tested against PostgreSQL in test_chat_history_pg.py.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.database.repositories import chat_history_repository as real_repo
from app.main import app
from app.services import chat_history_service as svc
from app.tests.test_rbac import User, env  # noqa: F401  (the RBAC environment fixture)


class FakeChatRepo:
    NotYours = real_repo.NotYours
    MAX_CONVERSATIONS = real_repo.MAX_CONVERSATIONS

    def __init__(self):
        self.convs = {}                      # thread_id -> {"farmer": pk, "messages": [...], ...}
        self.disabled = set()

    async def owner(self, thread_id):
        c = self.convs.get(thread_id)
        return (c is not None, c["farmer"] if c else None)

    async def record_turn(self, pk, thread_id, user_text, reply, *, language, input_mode, status, schemes):
        c = self.convs.get(thread_id)
        if c is not None and c["farmer"] != pk:
            raise real_repo.NotYours()
        now = datetime.now(timezone.utc)
        if c is None:
            c = self.convs[thread_id] = {"farmer": pk, "title": user_text[:120], "created_at": now, "messages": []}
        c["messages"] += [{"role": "USER", "content": user_text, "language": language, "input_mode": input_mode,
                           "status": None, "schemes": None, "created_at": now},
                          {"role": "ASSISTANT", "content": reply, "language": language, "input_mode": input_mode,
                           "status": status, "schemes": schemes, "created_at": now}]
        c["language"], c["last_activity_at"] = language, now

    def _summary(self, tid, c):
        return {"thread_id": tid, "title": c["title"], "language": c.get("language"),
                "message_count": len(c["messages"]), "created_at": c["created_at"],
                "last_activity_at": c.get("last_activity_at")}

    async def list_page(self, pk, limit, offset):
        mine = sorted(((t, c) for t, c in self.convs.items() if c["farmer"] == pk),
                      key=lambda tc: tc[1]["last_activity_at"], reverse=True)
        return [self._summary(t, c) for t, c in mine[offset:offset + limit]], len(mine)

    async def get(self, pk, thread_id, last=None):
        c = self.convs.get(thread_id)
        if c is None or c["farmer"] != pk:
            return None
        return {**self._summary(thread_id, c), "messages": c["messages"][-(last or 10_000):]}

    async def delete_one(self, pk, thread_id):
        c = self.convs.get(thread_id)
        if c is None or c["farmer"] != pk:
            return False
        del self.convs[thread_id]
        return True

    async def clear(self, pk):
        mine = [t for t, c in self.convs.items() if c["farmer"] == pk]
        for t in mine:
            del self.convs[t]
        return mine

    async def is_enabled(self, pk):
        return pk not in self.disabled

    async def set_enabled(self, pk, enabled):
        (self.disabled.discard if enabled else self.disabled.add)(pk)


class FakeAgent:
    """Stands in for the LangGraph pipeline: records what it was given, answers deterministically."""

    def __init__(self):
        self.calls, self.state = [], {}

    async def aget_state(self, config):
        return SimpleNamespace(values=self.state.get(config["configurable"]["thread_id"], {}))

    async def ainvoke(self, inputs, config=None):
        tid = config["configurable"]["thread_id"]
        self.calls.append((tid, [m.content for m in inputs["messages"]]))
        self.state.setdefault(tid, {"messages": []})["messages"] += inputs["messages"]
        return {"messages": [], "response_status": "schemes_found", "profile": {},
                "response_text": f"Answer to: {inputs['messages'][-1].content}",
                "response_schemes": [{"scheme_id": "PM_KISAN", "name": "PM-KISAN", "eligibility_status": "ELIGIBLE",
                                      "recommendation_section": "ELIGIBLE", "description": "not kept"}]}


@pytest.fixture
def chats(env, monkeypatch):                  # noqa: F811
    import app.api.chat as chat_api
    repo, agent = FakeChatRepo(), FakeAgent()

    async def pk_of(farmer_id):
        return next((f.id for f in env.auth.farmers.values() if f.farmer_id == farmer_id), None)
    monkeypatch.setattr(svc, "repo", repo)
    monkeypatch.setattr(svc, "get_farmer_pk", pk_of)
    monkeypatch.setattr(chat_api, "kisan_agent", agent)
    return SimpleNamespace(env=env, repo=repo, agent=agent)


def ask(user, text, thread):
    body = {"message": text, "thread_id": thread, "language": "en"}
    r = user.call("POST", "/chat", body) if user else TestClient(app).post("/chat", json=body)
    assert r.status_code == 200, r.text
    return r.json()


# ─── saving ──────────────────────────────────────────────────────────────────

def test_signed_in_turns_are_saved_and_listed(chats):
    me = User(chats.env, "FARMER")
    t = str(uuid.uuid4())
    ask(me, "I grow maize in Bihar", t)
    ask(me, "Which schemes for 2.5 acres?", t)
    rows = me.call("GET", "/farmers/me/conversations")
    assert rows.headers["X-Total-Count"] == "1"
    c = rows.json()[0]
    assert c["thread_id"] == t and c["title"] == "I grow maize in Bihar" and c["message_count"] == 4
    conv = me.call("GET", f"/farmers/me/conversations/{t}").json()
    assert [m["role"] for m in conv["messages"]] == ["USER", "ASSISTANT", "USER", "ASSISTANT"]
    assert conv["messages"][1]["content"] == "Answer to: I grow maize in Bihar"
    assert conv["messages"][1]["schemes"] == [{"scheme_id": "PM_KISAN", "name": "PM-KISAN",
                                               "recommendation_section": "ELIGIBLE", "eligibility_status": "ELIGIBLE"}]
    assert conv["messages"][0]["input_mode"] == "text" and conv["messages"][0]["language"] == "en"


def test_anonymous_chats_are_not_saved(chats):
    ask(None, "hello from a visitor", str(uuid.uuid4()))
    assert chats.repo.convs == {}


def test_turning_history_off_stops_saving(chats):
    me = User(chats.env, "FARMER")
    assert me.call("GET", "/farmers/me/chat-history-settings").json() == {"enabled": True}
    assert me.call("PUT", "/farmers/me/chat-history-settings", {"enabled": False}).json() == {"enabled": False}
    ask(me, "not to be kept", str(uuid.uuid4()))
    assert chats.repo.convs == {}
    me.call("PUT", "/farmers/me/chat-history-settings", {"enabled": True})
    ask(me, "kept again", str(uuid.uuid4()))
    assert len(chats.repo.convs) == 1


# ─── isolation ───────────────────────────────────────────────────────────────

def test_another_account_cannot_read_delete_or_continue(chats):
    a, b = User(chats.env, "FARMER"), User(chats.env, "FARMER")
    t = str(uuid.uuid4())
    ask(a, "my private question", t)
    assert b.call("GET", "/farmers/me/conversations").json() == []
    assert b.call("GET", f"/farmers/me/conversations/{t}").status_code == 404
    assert b.call("DELETE", f"/farmers/me/conversations/{t}").status_code == 404
    reply = ask(b, "continue their chat?", t)                       # B sends A's thread id to /chat
    assert reply["thread_id"] != t                                   # B gets a new conversation
    assert chats.agent.calls[-1][0] != t and "my private question" not in str(chats.agent.calls[-1])
    assert len(chats.repo.convs[t]["messages"]) == 2                 # A's conversation untouched
    assert b.call("GET", "/farmers/me/conversations").json()[0]["thread_id"] == reply["thread_id"]
    visitor = ask(None, "anonymous continue?", t)
    assert visitor["thread_id"] != t


def test_signed_out_requests_are_refused(chats):
    c = TestClient(app)
    for method, path in (("GET", "/farmers/me/conversations"), ("GET", "/farmers/me/conversations/x"),
                         ("DELETE", "/farmers/me/conversations"), ("GET", "/farmers/me/chat-history-settings")):
        assert c.request(method, path).status_code in (401, 403)


@pytest.mark.parametrize("bad", ["a b", "x" * 129, "../etc", "t;drop"])
def test_thread_id_is_validated(chats, bad):
    me = User(chats.env, "FARMER")
    assert me.call("GET", f"/farmers/me/conversations/{bad}").status_code in (404, 422)


# ─── continue / delete ───────────────────────────────────────────────────────

def test_reopened_conversation_continues_with_its_context(chats):
    me = User(chats.env, "FARMER")
    t = str(uuid.uuid4())
    ask(me, "I am from Bihar", t)
    chats.agent.state.clear()                                         # e.g. the server restarted
    ask(me, "and what about insurance?", t)
    tid, given = chats.agent.calls[-1]
    assert tid == t and given == ["I am from Bihar", "Answer to: I am from Bihar", "and what about insurance?"]
    ask(me, "and loans?", t)                                          # in-memory state is back: no duplicates
    assert chats.agent.calls[-1][1] == ["and loans?"]
    assert me.call("GET", f"/farmers/me/conversations/{t}").json()["message_count"] == 6


def test_delete_one_and_all(chats, monkeypatch):
    forgotten = []
    monkeypatch.setattr(svc, "_forget", forgotten.extend)            # the assistant's in-memory copy
    me = User(chats.env, "FARMER")
    t1, t2 = str(uuid.uuid4()), str(uuid.uuid4())
    ask(me, "first", t1)
    ask(me, "second", t2)
    assert me.call("DELETE", f"/farmers/me/conversations/{t1}").status_code == 204
    assert me.call("GET", f"/farmers/me/conversations/{t1}").status_code == 404
    assert me.call("DELETE", "/farmers/me/conversations").json() == {"deleted": 1}
    assert me.call("GET", "/farmers/me/conversations").json() == []
    assert forgotten == [t1, t2]


def test_saving_failure_never_breaks_the_chat(chats, monkeypatch):
    me = User(chats.env, "FARMER")

    async def broken(*a, **k):
        raise RuntimeError("database down")
    monkeypatch.setattr(chats.repo, "record_turn", broken)
    reply = ask(me, "still answered?", str(uuid.uuid4()))
    assert reply["reply"] == "Answer to: still answered?"


def test_record_turn_requires_text_and_reply():
    assert asyncio.run(svc.record_turn(None, "t", "q", {"reply": "a"}, language="en", input_mode="text")) is False
    assert asyncio.run(svc.record_turn("f", "t", " ", {"reply": "a"}, language="en", input_mode="text")) is False
    assert asyncio.run(svc.record_turn("f", "t", "q", {"reply": ""}, language="en", input_mode="text")) is False
