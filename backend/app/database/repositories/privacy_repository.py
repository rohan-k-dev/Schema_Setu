"""
PrivacyRepository — deleting a farmer's data and the retention purge (docs/PRIVACY.md).

Every statement is scoped to the account's integer PK, which the service takes from the
signed-in session. Each deletion runs in ONE transaction together with its audit event,
so either everything listed is gone or nothing is. Errors are raised, not swallowed.

Per-farmer tables (all ON DELETE CASCADE from farmers): farmer_profiles, search_history,
saved_schemes, saved_scheme_checklist_items, scheme_subscriptions, notification_preferences,
notifications, notification_deliveries, auth_sessions, auth_tokens, refresh_tokens.
review_cases.farmer_id is ON DELETE SET NULL (cases are kept, anonymised — see delete_account).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from psycopg import sql
from psycopg.rows import dict_row

from app.core.permissions import Principal
from app.database.connection import get_db_connection
from app.database.repositories import audit_repository

# What a deleted case keeps: scheme, reason, rules evidence (public scheme text), decision.
_ANONYMISE_CASE = ("query = '', profile_snapshot = '{}'::jsonb, farmer_id = NULL, updated_at = now()")


class LastAdmin(Exception):
    """The last active administrator can't delete their account."""


async def _count_in(cur, table: str, pk: int) -> int:
    await cur.execute(sql.SQL("SELECT count(*) AS n FROM {} WHERE farmer_id = %s").format(sql.Identifier(table)), (pk,))
    return (await cur.fetchone())["n"]


async def sessions(pk: int) -> List[Dict[str, Any]]:
    """The account's sign-in sessions (for the export; no token hashes)."""
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT created_at, last_seen_at, expires_at, revoked_at, revoked_reason, ip_address "
                "FROM auth_sessions WHERE farmer_id = %s ORDER BY created_at DESC LIMIT 200", (pk,))
            return [dict(r) for r in await cur.fetchall()]


async def delete_profile(pk: int, actor: Principal) -> Dict[str, int]:
    """Delete the saved profile (and with it the consent) and the search history recorded under it."""
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("DELETE FROM farmer_profiles WHERE farmer_id = %s", (pk,))
                profile = cur.rowcount
                await cur.execute("DELETE FROM search_history WHERE farmer_id = %s", (pk,))
                out = {"profile": profile, "search_history": cur.rowcount}
                await audit_repository.insert(cur, actor, "PROFILE_DELETED", "account", actor.farmer_id, out)
                return out


async def delete_saved_schemes(pk: int, actor: Principal) -> Dict[str, int]:
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                items = await _count_in(cur, "saved_scheme_checklist_items", pk)
                await cur.execute("DELETE FROM saved_schemes WHERE farmer_id = %s", (pk,))
                out = {"saved_schemes": cur.rowcount, "checklist_items": items}
                await audit_repository.insert(cur, actor, "SAVED_SCHEMES_DELETED", "account", actor.farmer_id, out)
                return out


async def delete_notification_data(pk: int, actor: Principal) -> Dict[str, int]:
    """Preferences (incl. SMS consent), followed schemes, messages + queued deliveries, the phone number."""
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                out = {}
                for table in ("notification_preferences", "scheme_subscriptions", "notifications"):
                    await cur.execute(sql.SQL("DELETE FROM {} WHERE farmer_id = %s").format(sql.Identifier(table)),
                                      (pk,))
                    out[table] = cur.rowcount
                await cur.execute("DELETE FROM auth_tokens WHERE farmer_id = %s AND purpose = 'verify_phone'", (pk,))
                await cur.execute("UPDATE farmers SET phone = NULL, phone_verified_at = NULL, updated_at = now() "
                                  "WHERE id = %s AND phone IS NOT NULL", (pk,))
                out["phone"] = cur.rowcount
                await audit_repository.insert(cur, actor, "NOTIFICATION_DATA_DELETED", "account", actor.farmer_id, out)
                return out


async def delete_account(pk: int, actor: Principal) -> Dict[str, Any]:
    """
    Delete the account and everything linked to it, in one transaction:
      - review cases the farmer raised: unlinked and anonymised (question and profile details removed);
      - open cases assigned to them (a reviewer): returned to the queue;
      - their read grants (as a reviewer): removed;
      - the account row: every per-farmer table cascades (profile, history, saved schemes, checklists,
        notifications, deliveries, subscriptions, sessions, tokens);
      - one ACCOUNT_DELETED audit event that names the account id only (no e-mail).
    Returns the review-case session ids, so the in-memory chat conversations can be cleared too.
    """
    last_admin = False      # raised after the block: get_db_connection re-wraps errors raised inside it
    result: Dict[str, Any] = {"deleted": False}
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT id FROM farmers WHERE (role = 'ADMIN' AND is_active) OR id = %s "
                                  "ORDER BY id FOR UPDATE", (pk,))
                await cur.execute("SELECT * FROM farmers WHERE id = %s", (pk,))
                me = await cur.fetchone()
                if me is not None:
                    await cur.execute("SELECT count(*) AS n FROM farmers WHERE role = 'ADMIN' AND is_active")
                    admins = (await cur.fetchone())["n"]
                    if me["role"] == "ADMIN" and me["is_active"] and admins <= 1:
                        last_admin = True
                    else:
                        counts, threads = await _delete_account_rows(cur, pk, me, actor)
                        result = {"deleted": True, "counts": counts, "chat_threads": threads}
    if last_admin:
        raise LastAdmin()
    return result


async def _delete_account_rows(cur, pk: int, me: dict, actor: Principal):
    """The deletion itself, inside delete_account's transaction."""
    counts: Dict[str, Any] = {}
    for table in ("search_history", "saved_schemes", "saved_scheme_checklist_items", "notifications",
                  "scheme_subscriptions", "auth_sessions"):
        counts[table] = await _count_in(cur, table, pk)
    counts["profile"] = await _count_in(cur, "farmer_profiles", pk)

    await cur.execute("UPDATE review_cases SET " + _ANONYMISE_CASE + " WHERE farmer_id = %s "
                      "RETURNING session_id", (pk,))
    threads = [r["session_id"] for r in await cur.fetchall()]
    counts["review_cases_anonymised"] = len(threads)
    await cur.execute("UPDATE review_cases SET status = 'PENDING', assignee = NULL, assigned_at = NULL, "
                      "awaiting_verification = false, version = version + 1, updated_at = now() "
                      "WHERE assignee = %s AND status IN ('PENDING', 'IN_REVIEW') RETURNING case_id",
                      (me["email"],))
    released = [r["case_id"] for r in await cur.fetchall()]
    for case_id in released:
        await cur.execute("INSERT INTO review_case_events (case_id, event, actor, from_status, to_status, note) "
                          "VALUES (%s, 'UNASSIGNED', 'system', 'IN_REVIEW', 'PENDING', "
                          "'The reviewer account was deleted.')", (case_id,))
    counts["review_cases_released"] = len(released)

    await cur.execute("DELETE FROM farmers WHERE id = %s", (pk,))
    await audit_repository.insert(cur, actor, "ACCOUNT_DELETED", "account", me["farmer_id"], dict(counts))
    return counts, threads


async def purge_expired(session_days: int, token_days: int, notification_days: int,
                        review_case_days: int, history_days: int) -> Dict[str, int]:
    """The retention rules for data that outlives its purpose (docs/PRIVACY.md)."""
    out: Dict[str, int] = {}
    statements = {
        "auth_sessions": ("DELETE FROM auth_sessions WHERE COALESCE(revoked_at, expires_at) "
                          "< now() - make_interval(days => %s)", session_days),
        "auth_tokens": ("DELETE FROM auth_tokens WHERE COALESCE(used_at, expires_at) "
                        "< now() - make_interval(days => %s)", token_days),
        "refresh_tokens": ("DELETE FROM refresh_tokens WHERE expires_at < now() - make_interval(days => %s)",
                           token_days),
        "search_history": ("DELETE FROM search_history WHERE searched_at < now() - make_interval(days => %s)",
                           history_days),
        "notifications": ("DELETE FROM notifications WHERE created_at < now() - make_interval(days => %s)",
                          notification_days),
        "review_cases": ("UPDATE review_cases SET " + _ANONYMISE_CASE + " WHERE status IN ('RESOLVED', 'DISMISSED') "
                         "AND updated_at < now() - make_interval(days => %s) "
                         "AND (query <> '' OR profile_snapshot <> '{}'::jsonb OR farmer_id IS NOT NULL)",
                         review_case_days),
    }
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor() as cur:
                for name, (sql, days) in statements.items():
                    await cur.execute(sql, (days,))
                    out[name] = cur.rowcount
    return out


async def account_pk(farmer_uuid: str) -> Optional[int]:
    async with get_db_connection() as conn:
        cur = await conn.execute("SELECT id FROM farmers WHERE farmer_id = %s", (farmer_uuid,))
        row = await cur.fetchone()
        return row[0] if row else None
