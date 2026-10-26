"""
NotificationRepository — subscriptions, preferences, in-app notifications, e-mail /
SMS deliveries and phone verification (docs/SCHEME_UPDATES.md).

Duplicates are prevented by the database:
  - one notification per account and change set: UNIQUE (farmer_id, dedupe_key);
  - one delivery per notification and channel:   UNIQUE (notification_id, channel);
  - a delivery is claimed for sending with FOR UPDATE SKIP LOCKED and moved to SENDING
    first, so two dispatchers never send the same delivery, and a SENT delivery is
    never picked up again.
Every account-facing query is filtered by the account's PK (from the session).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from psycopg import errors as pg_errors
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.database.connection import get_db_connection

PREF_COLUMNS = ("in_app", "email", "sms", "consequential_only", "sms_consent_at", "sms_consent_version",
                "sms_opted_out_at", "email_opted_out_at")
DEFAULT_PREFS = {"in_app": True, "email": False, "sms": False, "consequential_only": False,
                 "sms_consent_at": None, "sms_consent_version": None, "sms_opted_out_at": None,
                 "email_opted_out_at": None}


class PhoneInUse(Exception):
    """The phone number is verified on another account."""


async def _all(q, p=()) -> List[dict]:
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(q, p)
            return await cur.fetchall()


async def _write(q, p=()) -> List[dict]:
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(q, p)
            rows = await cur.fetchall() if cur.description else []
        await conn.commit()
    return rows


# ─── subscriptions ────────────────────────────────────────────────────────────

async def list_subscriptions(pk: int) -> List[dict]:
    return await _all("SELECT s.scheme_id, s.created_at, sc.name AS scheme_name FROM scheme_subscriptions s "
                      "LEFT JOIN schemes sc ON sc.scheme_id = s.scheme_id WHERE s.farmer_id = %s "
                      "ORDER BY s.created_at DESC", (pk,))


async def scheme_name(scheme_id: str) -> Optional[str]:
    rows = await _all("SELECT name FROM schemes WHERE scheme_id = %s", (scheme_id,))
    return rows[0]["name"] if rows else None


async def subscribe(pk: int, scheme_id: str) -> bool:
    rows = await _write("INSERT INTO scheme_subscriptions (farmer_id, scheme_id) VALUES (%s, %s) "
                        "ON CONFLICT DO NOTHING RETURNING scheme_id", (pk, scheme_id))
    return bool(rows)


async def unsubscribe(pk: int, scheme_id: str) -> bool:
    async with get_db_connection() as conn:
        cur = await conn.execute("DELETE FROM scheme_subscriptions WHERE farmer_id = %s AND scheme_id = %s",
                                 (pk, scheme_id))
        await conn.commit()
        return cur.rowcount > 0


# ─── preferences ──────────────────────────────────────────────────────────────

async def get_prefs(pk: int) -> Dict[str, Any]:
    rows = await _all("SELECT * FROM notification_preferences WHERE farmer_id = %s", (pk,))
    return {**DEFAULT_PREFS, **({k: rows[0][k] for k in PREF_COLUMNS} if rows else {})}


async def save_prefs(pk: int, changes: Dict[str, Any]) -> Dict[str, Any]:
    cols = [c for c in changes if c in PREF_COLUMNS]
    if len(cols) != len(changes):
        raise ValueError(f"unknown preference columns: {set(changes) - set(cols)}")
    insert = sql.SQL("INSERT INTO notification_preferences (farmer_id, {cols}) VALUES (%s, {vals}) "
                     "ON CONFLICT (farmer_id) DO UPDATE SET {sets}, updated_at = NOW()").format(
        cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
        vals=sql.SQL(", ").join(sql.Placeholder() * len(cols)),
        sets=sql.SQL(", ").join(sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(c), sql.Identifier(c))
                                for c in cols))
    await _write(insert, (pk, *[changes[c] for c in cols]))
    return await get_prefs(pk)


# ─── fan-out ──────────────────────────────────────────────────────────────────

async def audience(scheme_ids: Sequence[str]) -> List[dict]:
    """Active accounts that saved or subscribed to any of the schemes, with their preferences."""
    if not scheme_ids:
        return []
    return await _all(
        "WITH interest AS (SELECT farmer_id, scheme_id FROM saved_schemes WHERE scheme_id = ANY(%s) "
        "UNION SELECT farmer_id, scheme_id FROM scheme_subscriptions WHERE scheme_id = ANY(%s)) "
        "SELECT i.scheme_id, f.id AS farmer_pk, "
        "COALESCE(p.in_app, true) AS in_app, COALESCE(p.email, false) AS email, COALESCE(p.sms, false) AS sms, "
        "COALESCE(p.consequential_only, false) AS consequential_only "
        "FROM interest i JOIN farmers f ON f.id = i.farmer_id AND f.is_active "
        "LEFT JOIN notification_preferences p ON p.farmer_id = f.id ORDER BY f.id, i.scheme_id",
        (list(scheme_ids), list(scheme_ids)))


async def create_notification(n: Dict[str, Any], channels: Sequence[str]) -> Optional[int]:
    """Insert once per (account, dedupe_key) with its deliveries; None if it already existed."""
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "INSERT INTO notifications (farmer_id, scheme_id, batch_id, change_ids, title, body, consequential, "
                    "show_in_app, dedupe_key) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (farmer_id, dedupe_key) DO NOTHING RETURNING id",
                    (n["farmer_pk"], n["scheme_id"], n["batch_id"], Jsonb(n["change_ids"]), n["title"][:200],
                     n["body"], n["consequential"], n["show_in_app"], n["dedupe_key"][:128]))
                row = await cur.fetchone()
                if not row:
                    return None
                for ch in channels:
                    await cur.execute("INSERT INTO notification_deliveries (notification_id, farmer_id, channel) "
                                      "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (row["id"], n["farmer_pk"], ch))
    return row["id"]


# ─── inbox ────────────────────────────────────────────────────────────────────

_INBOX_ALL = "FROM notifications WHERE farmer_id = %s AND show_in_app"
_INBOX_UNREAD = _INBOX_ALL + " AND read_at IS NULL"


async def inbox(pk: int, unread_only: bool, limit: int, offset: int) -> Tuple[List[dict], int, int]:
    where = _INBOX_UNREAD if unread_only else _INBOX_ALL
    total = (await _all("SELECT count(*) AS n " + where, (pk,)))[0]["n"]
    unread = (await _all("SELECT count(*) AS n " + _INBOX_UNREAD, (pk,)))[0]["n"]
    rows = await _all("SELECT * " + where + " ORDER BY created_at DESC, id DESC LIMIT %s OFFSET %s",
                      (pk, limit, offset))
    return rows, total, unread


async def mark_read(pk: int, notification_id: int) -> bool:
    rows = await _write("UPDATE notifications SET read_at = COALESCE(read_at, NOW()) WHERE id = %s "
                        "AND farmer_id = %s RETURNING id", (notification_id, pk))
    return bool(rows)


async def mark_all_read(pk: int) -> int:
    return len(await _write("UPDATE notifications SET read_at = NOW() WHERE farmer_id = %s AND read_at IS NULL "
                            "RETURNING id", (pk,)))


# ─── deliveries ───────────────────────────────────────────────────────────────

async def claim_due(limit: int) -> List[dict]:
    """Move due deliveries to SENDING (one dispatcher each) and return them with what's needed to send."""
    return await _write(
        "WITH due AS (SELECT id FROM notification_deliveries WHERE status IN ('PENDING', 'FAILED') "
        "AND next_attempt_at <= NOW() ORDER BY next_attempt_at, id LIMIT %s FOR UPDATE SKIP LOCKED) "
        "UPDATE notification_deliveries d SET status = 'SENDING', attempts = d.attempts + 1, "
        "last_attempt_at = NOW(), updated_at = NOW() FROM due, notifications n, farmers f "
        "WHERE d.id = due.id AND n.id = d.notification_id AND f.id = d.farmer_id "
        "RETURNING d.*, n.title, n.body, n.scheme_id, n.consequential, f.email, f.is_verified, f.is_active, "
        "f.phone, f.phone_verified_at", (limit,))


async def finish(delivery_id: int, status: str, *, provider_message_id: Optional[str] = None,
                 error: Optional[str] = None, next_attempt_at: Optional[datetime] = None) -> None:
    await _write(
        "UPDATE notification_deliveries SET status = %s, provider_message_id = COALESCE(%s, provider_message_id), "
        "last_error = %s, next_attempt_at = COALESCE(%s, next_attempt_at), "
        "sent_at = CASE WHEN %s IN ('SENT', 'DELIVERED') THEN NOW() ELSE sent_at END, updated_at = NOW() "
        "WHERE id = %s AND status = 'SENDING'",
        (status, provider_message_id, error, next_attempt_at, status, delivery_id))


async def abandon_stuck(older_than_minutes: int = 15) -> int:
    """SENDING for too long (the process died mid-send): the outcome is unknown, so it is NOT retried."""
    return len(await _write(
        "UPDATE notification_deliveries SET status = 'GAVE_UP', updated_at = NOW(), "
        "last_error = 'Outcome unknown (interrupted while sending); not retried to avoid a duplicate.' "
        "WHERE status = 'SENDING' AND last_attempt_at < NOW() - make_interval(mins => %s) RETURNING id",
        (older_than_minutes,)))


async def provider_status(message_id: str, status: str, error: Optional[str]) -> bool:
    """Delivery report from the SMS provider (only SENT → DELIVERED / UNDELIVERED)."""
    rows = await _write(
        "UPDATE notification_deliveries SET status = %s, last_error = %s, updated_at = NOW() "
        "WHERE provider_message_id = %s AND channel = 'SMS' AND status IN ('SENT', 'DELIVERED', 'UNDELIVERED') "
        "RETURNING id", (status, error, message_id))
    return bool(rows)


async def list_deliveries(status: Optional[str], channel: Optional[str], limit: int,
                          offset: int) -> Tuple[List[dict], int]:
    where, params = [], []
    for col, val in (("d.status", status), ("d.channel", channel)):
        if val:
            where.append(f"{col} = %s")
            params.append(val)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    total = (await _all("SELECT count(*) AS n FROM notification_deliveries d" + clause, tuple(params)))[0]["n"]
    rows = await _all(
        "SELECT d.id, d.notification_id, d.channel, d.status, d.attempts, d.next_attempt_at, d.last_attempt_at, "
        "d.sent_at, d.provider_message_id, d.last_error, n.scheme_id, f.farmer_id AS account "
        "FROM notification_deliveries d JOIN notifications n ON n.id = d.notification_id "
        "JOIN farmers f ON f.id = d.farmer_id" + clause + " ORDER BY d.id DESC LIMIT %s OFFSET %s",
        (*params, limit, offset))
    return rows, total


async def delivery_counts() -> Dict[str, int]:
    return {r["status"]: r["n"] for r in await _all(
        "SELECT status, count(*) AS n FROM notification_deliveries GROUP BY status")}


# ─── phone verification (auth_tokens, purpose verify_phone) ───────────────────

async def create_phone_code(pk: int, code_hash: str, phone: str, expires_at: datetime) -> None:
    async with get_db_connection() as conn:
        async with conn.transaction():
            await conn.execute("UPDATE auth_tokens SET used_at = NOW() WHERE farmer_id = %s AND "
                               "purpose = 'verify_phone' AND used_at IS NULL", (pk,))
            await conn.execute("INSERT INTO auth_tokens (farmer_id, purpose, token_hash, expires_at, target) "
                               "VALUES (%s, 'verify_phone', %s, %s, %s)", (pk, code_hash, expires_at, phone))


async def check_phone_code(pk: int, code_hash: str, max_attempts: int) -> Tuple[str, Optional[str]]:
    """('ok', phone) | ('wrong', None) | ('locked', None) | ('none', None). Sets the verified phone on 'ok'."""
    result, phone, in_use = "none", None, False
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT * FROM auth_tokens WHERE farmer_id = %s AND purpose = 'verify_phone' "
                                  "AND used_at IS NULL AND expires_at > NOW() ORDER BY id DESC LIMIT 1 FOR UPDATE",
                                  (pk,))
                tok = await cur.fetchone()
                if tok is None:
                    result = "none"
                elif tok["attempts"] >= max_attempts:
                    result = "locked"
                elif tok["token_hash"] != code_hash:
                    await cur.execute("UPDATE auth_tokens SET attempts = attempts + 1 WHERE id = %s", (tok["id"],))
                    result = "locked" if tok["attempts"] + 1 >= max_attempts else "wrong"
                else:
                    await cur.execute("UPDATE auth_tokens SET used_at = NOW() WHERE id = %s", (tok["id"],))
                    try:
                        async with conn.transaction():            # savepoint
                            await cur.execute("UPDATE farmers SET phone = %s, phone_verified_at = NOW(), "
                                              "updated_at = NOW() WHERE id = %s", (tok["target"], pk))
                    except pg_errors.UniqueViolation:
                        in_use = True
                    else:
                        # a new number needs new SMS consent
                        await cur.execute("UPDATE notification_preferences SET sms = false, sms_consent_at = NULL, "
                                          "sms_consent_version = NULL WHERE farmer_id = %s", (pk,))
                        result, phone = "ok", tok["target"]
    if in_use:
        raise PhoneInUse()
    return result, phone


async def remove_phone(pk: int) -> None:
    async with get_db_connection() as conn:
        async with conn.transaction():
            await conn.execute("UPDATE farmers SET phone = NULL, phone_verified_at = NULL, updated_at = NOW() "
                               "WHERE id = %s", (pk,))
            await conn.execute("UPDATE notification_preferences SET sms = false, sms_consent_at = NULL, "
                               "sms_consent_version = NULL, sms_opted_out_at = NOW() WHERE farmer_id = %s", (pk,))


async def account_pk_by_uuid(farmer_uuid: str) -> Optional[int]:
    rows = await _all("SELECT id FROM farmers WHERE farmer_id = %s", (farmer_uuid,))
    return rows[0]["id"] if rows else None


async def account_contact(pk: int) -> Optional[dict]:
    rows = await _all("SELECT id, farmer_id, email, is_verified, phone, phone_verified_at FROM farmers WHERE id = %s",
                      (pk,))
    return rows[0] if rows else None
