"""
Privacy and data settings API (docs/PRIVACY.md).

  GET  /privacy/policy                  public: what is collected, why, where it goes, retention, exceptions
  GET  /farmers/me/data                 what is stored about you (counts and filled profile fields)
  GET  /farmers/me/data/export          everything, as a JSON download (recent sign-in; audited; rate-limited)
  DELETE /farmers/me/profile            delete the saved profile (withdraws consent) + the search history
  DELETE /farmers/me/saved-schemes      delete all saved schemes and checklists
  DELETE /farmers/me/notification-data  delete notification settings, followed schemes, messages, phone
  POST /farmers/me/delete-account       delete the account and everything linked (password + typed confirmation)

Every /farmers/me route acts on the signed-in account only (no account id is accepted) and
writes need the X-CSRF-Token header. The data never leaves through a cache (no-store).
"""

import json
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.api.deps import ensure_recent_auth, require
from app.core import privacy
from app.core.config import settings
from app.core.exceptions import ConfigurationError, DatabaseError
from app.core.logging import get_logger
from app.core.permissions import Permission, Principal
from app.core.rate_limit import limiter
from app.services import privacy_service as svc

logger = get_logger(__name__)

router = APIRouter(tags=["Privacy and data"])

own_data = require(Permission.ACCOUNT_OWN_DATA)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"


async def _call(coro):
    try:
        return await coro
    except svc.PrivacyRejected as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})
    except (DatabaseError, ConfigurationError):
        raise HTTPException(status_code=503, detail={"code": "UNAVAILABLE",
                                                     "message": "Your data can't be reached right now. Nothing was "
                                                                "changed; please try again."})


@router.get("/privacy/policy", summary="What we collect, why, where it goes, and for how long")
async def policy():
    """Public; contains no personal data."""
    return privacy.policy()


@router.get("/farmers/me/data", summary="What is stored about you")
async def my_data(response: Response, principal: Principal = Depends(own_data)):
    _no_store(response)
    return await _call(svc.summary(principal))


@router.get("/farmers/me/data/export", summary="Download all your data (JSON)")
async def export(request: Request, principal: Principal = Depends(own_data)):
    """Needs a recent sign-in or password confirmation (403 REAUTH_REQUIRED). At most 5 an hour."""
    ensure_recent_auth(request, principal)
    if limiter.hit("data_export", principal.farmer_id, 5, 3600) is not None:
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED",
                                                     "message": "Too many exports. Please try again later."})
    data = await _call(svc.export(principal))
    return Response(content=json.dumps(data, ensure_ascii=False, indent=2), media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="schemesetu-my-data.json"',
                             "Cache-Control": "no-store, max-age=0", "Pragma": "no-cache"})


@router.delete("/farmers/me/profile", summary="Delete your saved profile (withdraws consent) and search history")
async def delete_profile(principal: Principal = Depends(require(Permission.PROFILE_OWN_WRITE))):
    """
    Withdrawing consent to keep your details: the saved profile and the searches recorded under it are
    deleted, the chat stops using or saving profile details, and searches are no longer recorded.
    """
    return {"deleted": await _call(svc.delete_profile(principal))}


@router.delete("/farmers/me/saved-schemes", summary="Delete all your saved schemes and checklists")
async def delete_saved(principal: Principal = Depends(require(Permission.SAVED_SCHEMES_OWN_WRITE))):
    return {"deleted": await _call(svc.delete_saved_schemes(principal))}


@router.delete("/farmers/me/notification-data",
               summary="Delete your notification settings, followed schemes, messages and phone number")
async def delete_notifications(principal: Principal = Depends(require(Permission.NOTIFICATIONS_OWN))):
    return {"deleted": await _call(svc.delete_notification_data(principal))}


class DeleteAccountRequest(BaseModel):
    model_config = {"extra": "forbid"}
    password: str = Field(min_length=1, max_length=128)
    confirm: str = Field(max_length=40, description='Type "DELETE MY ACCOUNT"')
    chat_thread_ids: List[str] = Field(default_factory=list, max_length=20,
                                       description="Conversations open in this browser, to clear them from memory")


@router.post("/farmers/me/delete-account", summary="Delete your account and all its data")
async def delete_account(req: DeleteAccountRequest, principal: Principal = Depends(own_data)):
    """
    Needs your password and the typed confirmation. Deletes the account and everything linked to it,
    signs you out everywhere, and anonymises checks by our team that your searches raised.
    Exceptions (security log, data already sent to external services, server logs, operator backups)
    are listed in GET /privacy/policy.
    """
    result = await _call(svc.delete_account(principal, req.password, req.confirm,
                                            [t[:100] for t in req.chat_thread_ids]))
    out = JSONResponse({"deleted": result.get("deleted", False), "summary": result.get("counts", {}),
                        "chat_conversations_cleared": result.get("chat_conversations_cleared", 0),
                        "still_kept": [e["what"] for e in privacy.EXCEPTIONS]})
    out.delete_cookie(settings.SESSION_COOKIE_NAME, path="/")
    return out
