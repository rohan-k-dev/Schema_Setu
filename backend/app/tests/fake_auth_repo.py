"""
In-memory stand-in for app.database.repositories.auth_repository (same function
names and semantics), so the account flows can be tested end to end through the
HTTP API without PostgreSQL. test_auth_repository_pg.py runs the real repository
against PostgreSQL.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.models.db.farmer_auth import AuthSessionRow, FarmerRow

PURPOSE_RESET_PASSWORD = "reset_password"


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class FakeAuthRepo:
    PURPOSE_RESET_PASSWORD = PURPOSE_RESET_PASSWORD

    def __init__(self):
        self.farmers: dict[int, FarmerRow] = {}
        self.sessions: dict[int, AuthSessionRow] = {}
        self.tokens: list[dict] = []
        self._ids = itertools.count(1)

    # accounts
    async def get_farmer_by_email(self, email: str) -> Optional[FarmerRow]:
        return next((f for f in self.farmers.values() if f.email == email.lower()), None)

    async def get_farmer_by_pk(self, pk: int) -> Optional[FarmerRow]:
        return self.farmers.get(pk)

    async def create_farmer(self, email, password_hash, full_name, phone) -> Optional[FarmerRow]:
        if await self.get_farmer_by_email(email) or (
                phone and any(f.phone == phone for f in self.farmers.values())):
            return None
        pk = next(self._ids)
        f = FarmerRow(id=pk, farmer_id=f"uuid-{pk}", email=email.lower(), password_hash=password_hash,
                      full_name=full_name, phone=phone, password_changed_at=_now())
        self.farmers[pk] = f
        return f

    def _update(self, pk, **fields):
        self.farmers[pk] = self.farmers[pk].model_copy(update=fields)

    async def record_login_failure(self, pk, max_failures, lock_minutes):
        f = self.farmers[pk]
        if f.failed_login_count + 1 >= max_failures:
            self._update(pk, failed_login_count=0, locked_until=_now() + timedelta(minutes=lock_minutes))
        else:
            self._update(pk, failed_login_count=f.failed_login_count + 1)

    async def record_login_success(self, pk, new_password_hash=None):
        f = self.farmers[pk]
        self._update(pk, failed_login_count=0, locked_until=None, last_login_at=_now(),
                     login_count=f.login_count + 1,
                     password_hash=new_password_hash or f.password_hash)

    # sessions
    async def create_session(self, pk, session_hash, user_agent_hash, ip_address, expires_at):
        sid = next(self._ids)
        now = _now()
        self.sessions[sid] = AuthSessionRow(id=sid, farmer_id=pk, session_hash=session_hash,
                                            user_agent_hash=user_agent_hash, ip_address=ip_address,
                                            created_at=now, last_seen_at=now, expires_at=expires_at)

    def session_by_hash(self, session_hash) -> Optional[AuthSessionRow]:
        return next((s for s in self.sessions.values() if s.session_hash == session_hash), None)

    async def get_live_session(self, session_hash):
        s = self.session_by_hash(session_hash)
        if not s or s.revoked_at or s.expires_at <= _now():
            return None
        return s, self.farmers[s.farmer_id]

    async def touch_session(self, session_id):
        self.sessions[session_id] = self.sessions[session_id].model_copy(update={"last_seen_at": _now()})

    async def mark_reauthenticated(self, session_id):
        self.sessions[session_id] = self.sessions[session_id].model_copy(update={"reauthenticated_at": _now()})

    async def revoke_session(self, session_hash, reason):
        s = self.session_by_hash(session_hash)
        if s and not s.revoked_at:
            self.sessions[s.id] = s.model_copy(update={"revoked_at": _now(), "revoked_reason": reason})

    async def revoke_all_sessions(self, pk, reason, except_session_id=None):
        n = 0
        for s in list(self.sessions.values()):
            if s.farmer_id == pk and not s.revoked_at and s.id != except_session_id:
                self.sessions[s.id] = s.model_copy(update={"revoked_at": _now(), "revoked_reason": reason})
                n += 1
        return n

    # tokens
    async def create_token(self, pk, purpose, token_hash, expires_at):
        for t in self.tokens:
            if t["farmer_id"] == pk and t["purpose"] == purpose and t["used_at"] is None:
                t["used_at"] = _now()
        self.tokens.append({"farmer_id": pk, "purpose": purpose, "token_hash": token_hash,
                            "expires_at": expires_at, "used_at": None})

    def _consume(self, token_hash, purpose):
        for t in self.tokens:
            if (t["token_hash"] == token_hash and t["purpose"] == purpose and t["used_at"] is None
                    and t["expires_at"] > _now()):
                t["used_at"] = _now()
                return t["farmer_id"]
        return None

    async def reset_password_with_token(self, token_hash, new_password_hash):
        pk = self._consume(token_hash, PURPOSE_RESET_PASSWORD)
        if pk is None:
            return None
        self._update(pk, password_hash=new_password_hash, password_changed_at=_now(),
                     failed_login_count=0, locked_until=None)
        await self.revoke_all_sessions(pk, "password_reset")
        return pk

    async def change_password(self, pk, new_password_hash):
        self._update(pk, password_hash=new_password_hash, password_changed_at=_now())
        await self.revoke_all_sessions(pk, "password_changed")
