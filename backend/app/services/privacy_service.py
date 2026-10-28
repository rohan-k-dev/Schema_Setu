"""
Privacy and data settings (docs/PRIVACY.md): what is stored about the signed-in farmer,
a full export, deleting by category, deleting the account, and the retention purge.

Everything is scoped to the signed-in account (Principal.account_pk / farmer_id, never a
client-supplied id). Deletions run in one transaction with their audit event
(privacy_repository); exports are audited too. The export reuses the same service
functions as the rest of the app, so it shows exactly what the app holds.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.core.permissions import Principal
from app.database.repositories import privacy_repository as repo

logger = get_logger(__name__)

DELETE_CONFIRMATION = "DELETE MY ACCOUNT"
EXPORT_FORMAT_VERSION = "1"


class PrivacyRejected(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def _plain(o):
    """JSON-safe copy (datetimes → ISO strings, pydantic models → dicts)."""
    if hasattr(o, "model_dump"):
        o = o.model_dump()
    if isinstance(o, dict):
        return {k: _plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_plain(v) for v in o]
    return _iso(o)


async def _safe(coro, default):
    """One section of the export; a failing section is reported, never silently empty."""
    try:
        return await coro, None
    except Exception as exc:
        logger.error(f"Data export section failed: {type(exc).__name__}")
        return default, "This part couldn't be loaded; please try again."


async def collect(principal: Principal) -> Dict[str, Any]:
    """Everything SchemeSetu stores about the signed-in account."""
    from app.services import auth_service, notification_service, profile_service, review_workflow,         saved_scheme_service
    notif_repo, history_repo = notification_service.repo, profile_service.history_repo

    pk, uuid = principal.account_pk, principal.farmer_id
    account = await auth_service.repo.get_farmer_by_pk(pk)
    profile, e1 = await _safe(profile_service.get_profile(uuid), None)
    history, e2 = await _safe(history_repo.list_page(pk, 50, 0), ([], 0))
    saved, e3 = await _safe(saved_scheme_service.list_saved_schemes(uuid), [])
    details = []
    for s in saved:
        d, _ = await _safe(saved_scheme_service.get_saved_scheme(uuid, s.scheme_id), None)
        details.append(d or s)
    prefs, e4 = await _safe(notif_repo.get_prefs(pk), None)
    subs, e5 = await _safe(notif_repo.list_subscriptions(pk), [])
    inbox, e6 = await _safe(notif_repo.inbox(pk, False, 1000, 0), ([], 0, 0))
    cases, e7 = await _safe(review_workflow.cases_for_farmer(pk), [])
    sessions, e8 = await _safe(repo.sessions(pk), [])
    chats, e9 = await _safe(_conversations(pk), [])
    errors = {k: v for k, v in {"profile": e1, "search_history": e2, "saved_schemes": e3, "notification_settings": e4,
                                "followed_schemes": e5, "notifications": e6, "review_cases": e7,
                                "sessions": e8, "chat_history": e9}.items() if v}
    return {
        "account": {"email": account.email, "full_name": account.full_name, "phone": account.phone,
                    "phone_verified_at": _iso(account.phone_verified_at), "role": account.role,
                    "email_verified": account.is_verified, "created_at": _iso(account.created_at),
                    "last_login_at": _iso(account.last_login_at)} if account else None,
        "profile": _plain(profile),
        "search_history": _plain(history[0]),
        "saved_schemes": _plain(details),
        "notification_settings": _plain(prefs),
        "followed_schemes": _plain(subs),
        "notifications": _plain(inbox[0]),
        "review_cases": _plain(cases),
        "sessions": _plain(sessions),
        "chat_history": _plain(chats),
        "errors": errors,
    }


async def _conversations(pk: int) -> List[Dict[str, Any]]:
    """Every saved conversation with its messages (docs/CHAT_HISTORY.md)."""
    from app.database.repositories import chat_history_repository as chats
    rows, _ = await chats.list_page(pk, chats.MAX_CONVERSATIONS, 0)
    return [await chats.get(pk, r["thread_id"]) or r for r in rows]


async def summary(principal: Principal) -> Dict[str, Any]:
    data = await collect(principal)
    prof = data["profile"] or {}
    filled = [f for f in ("state", "district", "land_size", "primary_crop", "other_crops", "farming_type",
                          "occupation", "age", "gender", "category", "income_range", "residence")
              if prof.get(f) not in (None, [], "")]
    return {
        "has_profile": data["profile"] is not None,
        "consent_given": bool(prof.get("consent_given")),
        "consent_given_at": prof.get("consent_given_at"),
        "profile_fields_filled": filled,
        "counts": {"search_history": len(data["search_history"]), "saved_schemes": len(data["saved_schemes"]),
                   "followed_schemes": len(data["followed_schemes"]), "notifications": len(data["notifications"]),
                   "review_cases": len(data["review_cases"]),
                   "open_review_cases": sum(1 for c in data["review_cases"] if c.get("open")),
                   "sessions": len(data["sessions"]), "chat_history": len(data["chat_history"])},
        "has_phone": bool(data["account"] and data["account"]["phone"]),
        "notification_settings": data["notification_settings"],
        "errors": data["errors"],
    }


async def export(principal: Principal) -> Dict[str, Any]:
    from app.core import privacy
    from app.database.repositories import audit_repository
    data = await collect(principal)
    await audit_repository.record(principal, "DATA_EXPORTED", "account", principal.farmer_id,
                                  {"sections": [k for k, v in data.items() if v and k != "errors"]})
    return {"format_version": EXPORT_FORMAT_VERSION, "generated_at": datetime.now(timezone.utc).isoformat(),
            "about": "Everything SchemeSetu stores about your account. Passwords are stored only as a hash and "
                     "are not included; sign-in tokens are not included.",
            "processors_note": privacy.PROCESSOR_NOTE, **data}


# ─── deletion ─────────────────────────────────────────────────────────────────

async def delete_profile(principal: Principal) -> Dict[str, int]:
    """Withdraws consent: deletes the saved profile and the search history kept under it."""
    return await repo.delete_profile(principal.account_pk, principal)


async def delete_saved_schemes(principal: Principal) -> Dict[str, int]:
    return await repo.delete_saved_schemes(principal.account_pk, principal)


async def delete_notification_data(principal: Principal) -> Dict[str, int]:
    return await repo.delete_notification_data(principal.account_pk, principal)


def forget_chat_threads(thread_ids: Iterable[str]) -> int:
    """Drop conversations from the assistant's in-memory store (saved copies are deleted separately)."""
    from app.graph.workflow import memory
    gone = 0
    for tid in {t for t in thread_ids if t}:
        if memory.storage.pop(tid, None) is not None:
            gone += 1
        for key in [k for k in getattr(memory, "writes", {}) if isinstance(k, tuple) and k and k[0] == tid]:
            memory.writes.pop(key, None)
    return gone


async def delete_account(principal: Principal, password: str, confirm: str,
                         thread_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Delete the account and all its data (docs/PRIVACY.md); needs the password and the typed confirmation."""
    from app.services import auth_service
    if (confirm or "").strip().upper() != DELETE_CONFIRMATION:
        raise PrivacyRejected("CONFIRMATION_REQUIRED", f"Type {DELETE_CONFIRMATION} to confirm.", 422)
    account = await auth_service.repo.get_farmer_by_pk(principal.account_pk)
    if account is None or not auth_service.verify_password(password or "", account.password_hash):
        await asyncio.sleep(0)               # same path whether or not the account still exists
        raise PrivacyRejected("INVALID_PASSWORD", "That password is not correct.", 400)
    # the deletion is audited under the account id only — never the e-mail of a deleted account
    actor = Principal(role=principal.role, label=f"account:{principal.farmer_id}", account_pk=None,
                      farmer_id=principal.farmer_id, via=principal.via, ip_address=None)
    try:
        result = await repo.delete_account(principal.account_pk, actor)
    except repo.LastAdmin:
        raise PrivacyRejected("LAST_ADMIN", "You are the last administrator: make another account an "
                                            "administrator before deleting yours.", 409)
    result["chat_conversations_cleared"] = forget_chat_threads((result.pop("chat_threads", None) or [])
                                                               + list(thread_ids or []))
    from app.core.rate_limit import limiter
    limiter.forget(account.email)
    return result


# ─── retention ────────────────────────────────────────────────────────────────

async def purge() -> Dict[str, int]:
    from app.database.repositories.search_history_repository import RETENTION_DAYS
    out = await repo.purge_expired(settings.RETENTION_SESSION_DAYS, settings.RETENTION_TOKEN_DAYS,
                                   settings.RETENTION_NOTIFICATION_DAYS, settings.RETENTION_REVIEW_CASE_DAYS,
                                   RETENTION_DAYS, settings.RETENTION_CHAT_DAYS)
    if any(out.values()):
        logger.info(f"Retention purge: {out}")
    return out


async def purge_loop(hours: int) -> None:
    """Apply the retention rules daily (one backend process)."""
    while True:
        try:
            await purge()
        except Exception as exc:
            logger.error(f"Retention purge failed: {type(exc).__name__}")
        await asyncio.sleep(hours * 3600)
