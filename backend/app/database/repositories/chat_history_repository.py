"""
ChatHistoryRepository — a signed-in farmer's saved conversations (docs/CHAT_HISTORY.md).

Tables (migration 0012): `sessions` = one conversation (thread_id, owner farmer_id, title, counts, times),
`messages` = its turns (USER / ASSISTANT text, language, input mode, reply status, schemes shown).

Every function takes the account's integer PK, which the service obtains from the authenticated session;
every statement is filtered by it, so a farmer can only list, open or delete their own conversations.
A thread that belongs to another account (or to no account) is never appended to. Errors are raised.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.database.connection import get_db_connection

MAX_CONVERSATIONS = 200          # per account; the least recently used beyond this are removed
MAX_MESSAGES = 400               # per conversation; older turns beyond this are removed
MAX_TEXT_CHARS = 8000
TITLE_CHARS = 120

class NotYours(Exception):
    """The thread belongs to another account (or to an anonymous conversation)."""


async def owner(thread_id: str) -> Tuple[bool, Optional[int]]:
    """(exists, farmer pk or None) for a thread id."""
    async with get_db_connection() as conn:
        cur = await conn.execute("SELECT farmer_id FROM sessions WHERE thread_id = %s", (thread_id,))
        row = await cur.fetchone()
        return (row is not None, row[0] if row else None)


async def record_turn(pk: int, thread_id: str, user_text: str, reply: str, *, language: str, input_mode: str,
                      status: Optional[str], schemes: Optional[List[Dict[str, Any]]]) -> None:
    """Append one question + answer to the farmer's conversation (created on its first turn)."""
    not_yours = False
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT id, farmer_id FROM sessions WHERE thread_id = %s FOR UPDATE", (thread_id,))
                row = await cur.fetchone()
                if row is not None and row["farmer_id"] != pk:
                    not_yours = True
                else:
                    if row is None:
                        await cur.execute(
                            "INSERT INTO sessions (thread_id, farmer_id, language, title) VALUES (%s, %s, %s, %s) "
                            "RETURNING id",
                            (thread_id, pk, language, " ".join(user_text.split())[:TITLE_CHARS] or None))
                        session_pk = (await cur.fetchone())["id"]
                    else:
                        session_pk = row["id"]
                    await cur.execute(
                        "INSERT INTO messages (session_id, role, content, language, input_mode) "
                        "VALUES (%s, 'USER', %s, %s, %s)",
                        (session_pk, user_text[:MAX_TEXT_CHARS], language, input_mode))
                    await cur.execute(
                        "INSERT INTO messages (session_id, role, content, language, input_mode, status, schemes) "
                        "VALUES (%s, 'ASSISTANT', %s, %s, %s, %s, %s)",
                        (session_pk, reply[:MAX_TEXT_CHARS], language, input_mode, status,
                         Jsonb(schemes) if schemes else None))
                    await cur.execute(
                        "DELETE FROM messages WHERE session_id = %s AND id NOT IN "
                        "(SELECT id FROM messages WHERE session_id = %s ORDER BY id DESC LIMIT %s)",
                        (session_pk, session_pk, MAX_MESSAGES))
                    await cur.execute(
                        "UPDATE sessions SET message_count = (SELECT count(*) FROM messages WHERE session_id = %s), "
                        "language = %s, last_activity_at = now(), updated_at = now() WHERE id = %s",
                        (session_pk, language, session_pk))
                    await cur.execute(
                        "DELETE FROM sessions WHERE farmer_id = %s AND id NOT IN (SELECT id FROM sessions "
                        "WHERE farmer_id = %s ORDER BY last_activity_at DESC, id DESC LIMIT %s)",
                        (pk, pk, MAX_CONVERSATIONS))
    if not_yours:
        raise NotYours()


async def list_page(pk: int, limit: int, offset: int) -> Tuple[List[Dict[str, Any]], int]:
    """The farmer's conversations, most recently active first, and the total count."""
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT count(*) AS n FROM sessions WHERE farmer_id = %s", (pk,))
            total = (await cur.fetchone())["n"]
            await cur.execute("SELECT thread_id, title, language, message_count, created_at, last_activity_at FROM sessions WHERE farmer_id = %s "
                              "ORDER BY last_activity_at DESC, id DESC LIMIT %s OFFSET %s", (pk, limit, offset))
            return [dict(r) for r in await cur.fetchall()], total


async def get(pk: int, thread_id: str, last: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """One of the farmer's conversations with its messages (oldest first); None if not theirs / missing."""
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT id, thread_id, title, language, message_count, created_at, last_activity_at FROM sessions "
                              "WHERE thread_id = %s AND farmer_id = %s",
                              (thread_id, pk))
            conv = await cur.fetchone()
            if conv is None:
                return None
            await cur.execute(
                "SELECT * FROM (SELECT id, role, content, language, input_mode, status, schemes, created_at "
                "FROM messages WHERE session_id = %s ORDER BY id DESC LIMIT %s) m ORDER BY id",
                (conv["id"], last or MAX_MESSAGES))
            out = dict(conv)
            out.pop("id")
            out["messages"] = [dict(m) for m in await cur.fetchall()]
            return out


async def delete_one(pk: int, thread_id: str) -> bool:
    async with get_db_connection() as conn:
        cur = await conn.execute("DELETE FROM sessions WHERE thread_id = %s AND farmer_id = %s", (thread_id, pk))
        await conn.commit()
        return cur.rowcount > 0


async def clear(pk: int) -> List[str]:
    """Delete all of the farmer's conversations; returns their thread ids (to clear the in-memory store too)."""
    async with get_db_connection() as conn:
        cur = await conn.execute("DELETE FROM sessions WHERE farmer_id = %s RETURNING thread_id", (pk,))
        await conn.commit()
        return [r[0] for r in await cur.fetchall()]


async def thread_ids(pk: int) -> List[str]:
    async with get_db_connection() as conn:
        cur = await conn.execute("SELECT thread_id FROM sessions WHERE farmer_id = %s", (pk,))
        return [r[0] for r in await cur.fetchall()]


async def is_enabled(pk: int) -> bool:
    async with get_db_connection() as conn:
        cur = await conn.execute("SELECT chat_history_enabled FROM farmers WHERE id = %s", (pk,))
        row = await cur.fetchone()
        return bool(row and row[0])


async def set_enabled(pk: int, enabled: bool) -> None:
    async with get_db_connection() as conn:
        await conn.execute("UPDATE farmers SET chat_history_enabled = %s, updated_at = now() WHERE id = %s",
                           (enabled, pk))
        await conn.commit()
