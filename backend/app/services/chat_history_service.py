"""
Chat history for signed-in farmers (docs/CHAT_HISTORY.md).

- Every chat / voice turn of a signed-in account is saved (question as the farmer typed it, or the voice
  transcript; the reply as shown, in the reply language; a small snapshot of the schemes shown), unless
  the account turned chat history off. Anonymous conversations are never stored.
- A thread id the browser sends is used only when it is new or the farmer's own conversation; one owned by
  another account (or anyone, for a signed-out visitor) gets a fresh thread — conversations can't be read
  or continued by guessing an id.
- Reopening a saved conversation continues it: when the in-memory conversation state is gone (e.g. after
  a restart) the last turns are given back to the assistant as context.
Saving never breaks the chat: errors are logged and the reply is returned as usual.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional, Tuple

from app.core.logging import get_logger
from app.database.repositories import chat_history_repository as repo
from app.database.repositories.farmer_repository import get_farmer_pk

logger = get_logger(__name__)

CONTEXT_TURNS = 10                 # stored messages given back to the assistant when continuing a chat
_SCHEME_FIELDS = ("scheme_id", "name", "recommendation_section", "eligibility_status")


def _schemes_snapshot(schemes: Optional[List[Dict[str, Any]]]) -> Optional[List[Dict[str, Any]]]:
    if not schemes:
        return None
    return [{k: s.get(k) for k in _SCHEME_FIELDS if s.get(k) is not None} for s in schemes[:60]
            if isinstance(s, dict)]


async def resolve_thread(farmer_id: Optional[str], thread_id: str) -> str:
    """The thread to use: the requested one if it's new or this farmer's own, else a fresh id."""
    try:
        exists, owner_pk = await repo.owner(thread_id)
    except Exception as exc:                       # no database: nothing stored, nothing to protect
        logger.warning(f"Chat history lookup unavailable ({type(exc).__name__}); using the thread as given.")
        return thread_id
    if not exists:
        return thread_id
    pk = await get_farmer_pk(farmer_id) if farmer_id else None
    if pk is not None and owner_pk == pk:
        return thread_id
    logger.info("Thread id belongs to another conversation owner; starting a new conversation.")
    return str(uuid.uuid4())


async def context_messages(farmer_id: Optional[str], thread_id: str) -> List[Tuple[str, str]]:
    """The last stored turns of the farmer's own conversation, as (role, text) for the assistant's context."""
    if not farmer_id:
        return []
    try:
        pk = await get_farmer_pk(farmer_id)
        conv = await repo.get(pk, thread_id, last=CONTEXT_TURNS) if pk else None
    except Exception as exc:
        logger.warning(f"Chat history context unavailable ({type(exc).__name__}).")
        return []
    if not conv:
        return []
    return [("human" if m["role"] == "USER" else "ai", m["content"]) for m in conv["messages"]]


async def record_turn(farmer_id: Optional[str], thread_id: str, user_text: str, response: Dict[str, Any], *,
                      language: str, input_mode: str) -> bool:
    """Save one question + answer for a signed-in farmer. Never raises. True if stored."""
    reply = (response or {}).get("reply") or ""
    if not farmer_id or not (user_text or "").strip() or not reply.strip():
        return False
    try:
        pk = await get_farmer_pk(farmer_id)
        if not pk or not await repo.is_enabled(pk):
            return False
        await repo.record_turn(pk, thread_id, user_text.strip(), reply, language=(language or "en")[:10],
                               input_mode=input_mode, status=response.get("status"),
                               schemes=_schemes_snapshot(response.get("schemes")))
        return True
    except repo.NotYours:
        logger.warning("Chat turn not saved: the thread belongs to another conversation owner.")
        return False
    except Exception as exc:
        logger.error(f"Chat history not saved ({type(exc).__name__}).")
        return False


# ─── the farmer's own history (API) ───────────────────────────────────────────

class ChatHistoryError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


async def _pk(farmer_id: str) -> int:
    pk = await get_farmer_pk(farmer_id)
    if pk is None:
        raise ChatHistoryError("NOT_FOUND", "Account not found.", 404)
    return pk


async def list_conversations(farmer_id: str, limit: int, offset: int):
    return await repo.list_page(await _pk(farmer_id), limit, offset)


async def get_conversation(farmer_id: str, thread_id: str) -> Dict[str, Any]:
    conv = await repo.get(await _pk(farmer_id), thread_id)
    if conv is None:                             # another farmer's conversation looks exactly like a missing one
        raise ChatHistoryError("NOT_FOUND", "Conversation not found.", 404)
    return conv


async def delete_conversation(farmer_id: str, thread_id: str) -> None:
    if not await repo.delete_one(await _pk(farmer_id), thread_id):
        raise ChatHistoryError("NOT_FOUND", "Conversation not found.", 404)
    _forget([thread_id])


async def clear_conversations(farmer_id: str) -> int:
    threads = await repo.clear(await _pk(farmer_id))
    _forget(threads)
    return len(threads)


async def get_settings(farmer_id: str) -> Dict[str, bool]:
    return {"enabled": await repo.is_enabled(await _pk(farmer_id))}


async def set_settings(farmer_id: str, enabled: bool) -> Dict[str, bool]:
    await repo.set_enabled(await _pk(farmer_id), enabled)
    return {"enabled": enabled}


def _forget(thread_ids: List[str]) -> None:
    """A deleted conversation is also dropped from the assistant's in-memory state."""
    from app.services.privacy_service import forget_chat_threads
    forget_chat_threads(thread_ids)
