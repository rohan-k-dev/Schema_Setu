"""
AdminRepository — SQL for account administration and scheme curation (docs/RBAC.md).

Every change and its audit event are written in ONE transaction. Role and status
changes lock the affected rows, so two administrators acting at the same time can't
remove the last active administrator, and they revoke the target's sessions (the next
request must sign in again under the new role / status).

Rejections are recorded in a variable and raised after the connection block has
closed (get_db_connection() re-raises anything thrown inside it as DatabaseError);
nothing has been written at that point, so the transaction commits no change.
"""

from __future__ import annotations

from typing import Any, List, Optional, Tuple

from psycopg import sql
from psycopg.rows import dict_row

from app.core.permissions import Principal, Role
from app.database.connection import get_db_connection
from app.database.repositories import audit_repository as audit
from app.models.db import SchemeRow
from app.models.db.farmer_auth import FarmerRow

CURATION_COLUMNS = ("status", "needs_review", "review_notes")


class AdminRejected(Exception):
    """A rule of account administration was broken; ``code`` maps to the HTTP status."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


_NOT_FOUND = ("NOT_FOUND", "Account not found.")
_SELF = ("SELF_CHANGE", "You can't change your own role or account status.")
_LAST_ADMIN = ("LAST_ADMIN", "This is the last active administrator. Make another account an "
                             "administrator first.")


async def list_accounts(limit: int, offset: int, role: Optional[str] = None,
                        query: Optional[str] = None) -> Tuple[List[FarmerRow], int]:
    where, params = [], []
    if role:
        where.append("role = %s")
        params.append(role)
    if query:
        where.append("(email ILIKE %s OR full_name ILIKE %s)")
        like = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        params += [like, like]
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT count(*) AS n FROM farmers" + clause, params)
            total = (await cur.fetchone())["n"]
            await cur.execute("SELECT * FROM farmers" + clause + " ORDER BY created_at DESC, id DESC "
                              "LIMIT %s OFFSET %s", [*params, limit, offset])
            rows = await cur.fetchall()
    return [FarmerRow(**r) for r in rows], total


async def get_account(farmer_id: str) -> Optional[FarmerRow]:
    async with get_db_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT * FROM farmers WHERE farmer_id = %s", (farmer_id,))
            row = await cur.fetchone()
    return FarmerRow(**row) if row else None


async def _lock_target_and_admins(cur, farmer_id: str) -> Tuple[Optional[dict], int]:
    """Lock the active administrators and the target (always in id order: no deadlocks)."""
    await cur.execute("SELECT id FROM farmers WHERE (role = 'ADMIN' AND is_active) OR farmer_id = %s "
                      "ORDER BY id FOR UPDATE", (farmer_id,))
    await cur.execute("SELECT * FROM farmers WHERE farmer_id = %s", (farmer_id,))
    target = await cur.fetchone()
    await cur.execute("SELECT count(*) AS n FROM farmers WHERE role = 'ADMIN' AND is_active")
    return target, (await cur.fetchone())["n"]


async def _revoke_sessions(cur, account_pk: int, reason: str) -> None:
    await cur.execute("UPDATE auth_sessions SET revoked_at = NOW(), revoked_reason = %s "
                      "WHERE farmer_id = %s AND revoked_at IS NULL", (reason, account_pk))


async def set_role(actor: Principal, farmer_id: str, new_role: Role,
                   expected_role: Optional[Role]) -> FarmerRow:
    rejected: Optional[tuple] = None
    row = None
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                target, admins = await _lock_target_and_admins(cur, farmer_id)
                if target is None:
                    rejected = _NOT_FOUND
                elif target["id"] == actor.account_pk:
                    rejected = _SELF
                elif expected_role is not None and target["role"] != expected_role.value:
                    rejected = ("CONFLICT", f"The role was changed meanwhile (it is now {target['role']}). "
                                            "Reload and try again.")
                elif target["role"] == new_role.value:
                    row = target                                  # nothing to change
                elif target["role"] == Role.ADMIN.value and target["is_active"] and admins <= 1:
                    rejected = _LAST_ADMIN
                else:
                    # a role change always clears reviewer approval: it must be granted again
                    await cur.execute("UPDATE farmers SET role = %s, reviewer_approved_at = NULL, "
                                      "reviewer_approved_by = NULL, updated_at = NOW() WHERE id = %s "
                                      "RETURNING *", (new_role.value, target["id"]))
                    row = await cur.fetchone()
                    await _end_review_grants(cur, target["id"], actor.label)
                    await _revoke_sessions(cur, target["id"], "role_changed")
                    await audit.insert(cur, actor, "ROLE_CHANGED", "account", farmer_id,
                                       {"from": target["role"], "to": new_role.value})
    if rejected:
        raise AdminRejected(*rejected)
    return FarmerRow(**row)


async def _end_review_grants(cur, account_pk: int, by: str) -> None:
    await cur.execute("UPDATE review_case_grants SET revoked_at = NOW(), revoked_by = %s "
                      "WHERE reviewer_id = %s AND revoked_at IS NULL", (by, account_pk))


async def set_reviewer_approval(actor: Principal, farmer_id: str, approved: bool) -> FarmerRow:
    """
    Approve or revoke a REVIEWER account (docs/HUMAN_REVIEW.md, Access policy). Revoking ends the
    account's sessions and its case grants, in the same transaction as the audit event.
    """
    rejected: Optional[tuple] = None
    row = None
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                target, _ = await _lock_target_and_admins(cur, farmer_id)
                if target is None:
                    rejected = _NOT_FOUND
                elif target["id"] == actor.account_pk:
                    rejected = _SELF
                elif target["role"] != Role.REVIEWER.value:
                    rejected = ("NOT_A_REVIEWER", "Only REVIEWER accounts can be approved for review work.")
                elif approved and not (target["is_active"] and target["is_verified"]):
                    rejected = ("NOT_ELIGIBLE", "The account must be active and have a verified e-mail.")
                elif bool(target["reviewer_approved_at"]) == approved:
                    row = target
                else:
                    await cur.execute(
                        "UPDATE farmers SET reviewer_approved_at = CASE WHEN %s THEN NOW() END, "
                        "reviewer_approved_by = CASE WHEN %s THEN %s END, updated_at = NOW() "
                        "WHERE id = %s RETURNING *", (approved, approved, actor.label, target["id"]))
                    row = await cur.fetchone()
                    if not approved:
                        await _revoke_sessions(cur, target["id"], "reviewer_approval_revoked")
                        await _end_review_grants(cur, target["id"], actor.label)
                    await audit.insert(cur, actor, "REVIEWER_APPROVED" if approved else "REVIEWER_APPROVAL_REVOKED",
                                       "account", farmer_id, {})
    if rejected:
        raise AdminRejected(*rejected)
    return FarmerRow(**row)


async def set_active(actor: Principal, farmer_id: str, is_active: bool) -> FarmerRow:
    rejected: Optional[tuple] = None
    row = None
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                target, admins = await _lock_target_and_admins(cur, farmer_id)
                if target is None:
                    rejected = _NOT_FOUND
                elif target["id"] == actor.account_pk:
                    rejected = _SELF
                elif target["is_active"] == is_active:
                    row = target
                elif not is_active and target["role"] == Role.ADMIN.value and admins <= 1:
                    rejected = _LAST_ADMIN
                else:
                    await cur.execute("UPDATE farmers SET is_active = %s, updated_at = NOW() WHERE id = %s "
                                      "RETURNING *", (is_active, target["id"]))
                    row = await cur.fetchone()
                    if not is_active:
                        await _revoke_sessions(cur, target["id"], "account_deactivated")
                    await audit.insert(cur, actor, "ACCOUNT_REACTIVATED" if is_active else "ACCOUNT_DEACTIVATED",
                                       "account", farmer_id, {"role": target["role"]})
    if rejected:
        raise AdminRejected(*rejected)
    return FarmerRow(**row)


async def curate_scheme(actor: Principal, scheme_id: str, changes: dict[str, Any]) -> Optional[SchemeRow]:
    """Change curation flags of a scheme; None if it doesn't exist. Audited with before / after."""
    cols = [c for c in changes if c in CURATION_COLUMNS]
    if len(cols) != len(changes):
        raise ValueError(f"not a curation column: {set(changes) - set(cols)}")
    async with get_db_connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("SELECT * FROM schemes WHERE scheme_id = %s FOR UPDATE", (scheme_id,))
                before = await cur.fetchone()
                if before is None:
                    return None
                query = sql.SQL("UPDATE schemes SET {}, updated_at = NOW() WHERE id = %s RETURNING *").format(
                    sql.SQL(", ").join(sql.SQL("{} = {}").format(sql.Identifier(c), sql.Placeholder())
                                       for c in cols))
                await cur.execute(query, (*[changes[c] for c in cols], before["id"]))
                after = await cur.fetchone()
                await audit.insert(cur, actor, "SCHEME_CURATED", "scheme", scheme_id, {
                    "before": {c: before[c] for c in cols}, "after": {c: after[c] for c in cols}})
    return SchemeRow(**after)
