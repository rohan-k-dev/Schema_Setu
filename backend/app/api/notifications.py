"""
Notifications API (docs/SCHEME_UPDATES.md).

Signed-in, own account only (``notifications:own``; PUT/POST/DELETE need X-CSRF-Token):
  /farmers/me/notifications …            in-app inbox, mark read
  /farmers/me/notification-preferences   channels, consequential-only, SMS consent / opt-out
  /farmers/me/subscriptions/{scheme_id}  follow / unfollow a scheme (saved schemes count too)
  /farmers/me/phone …                    verify a phone number by SMS code
Public, but each request proves itself:
  POST /notifications/unsubscribe        one-click e-mail unsubscribe (signed token from the e-mail)
  POST /notifications/sms-status         SMS provider delivery reports (HMAC signature)
"""

from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, Response, status
from pydantic import BaseModel, Field, StrictBool

from app.api.deps import require
from app.core.exceptions import ConfigurationError, DatabaseError
from app.core.permissions import Permission, Principal
from app.core.rate_limit import limiter
from app.database.repositories import audit_repository
from app.database.repositories import notification_repository as repo
from app.services import notification_channels as channels
from app.services import notification_service as svc

router = APIRouter(tags=["Notifications"])
own = require(Permission.NOTIFICATIONS_OWN)

SchemeIdPath = Annotated[str, Path(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_\-]+$")]


async def _call(coro):
    try:
        return await coro
    except svc.NotifyRejected as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})
    except (DatabaseError, ConfigurationError):
        raise HTTPException(status_code=503, detail={"code": "NOTIFICATIONS_UNAVAILABLE",
                                                     "message": "Notifications are unavailable right now."})


def _rate(bucket: str, key: str, limit: int, window: int) -> None:
    if limiter.hit(bucket, key, limit, window) is not None:
        raise HTTPException(status_code=429, detail={"code": "RATE_LIMITED",
                                                     "message": "Too many attempts. Please wait and try again."})


# ─── inbox ────────────────────────────────────────────────────────────────────

def _n(row: dict) -> dict:
    return {"id": row["id"], "scheme_id": row["scheme_id"], "title": row["title"], "body": row["body"],
            "consequential": row["consequential"], "created_at": row["created_at"].isoformat(),
            "read": row["read_at"] is not None}


@router.get("/farmers/me/notifications", summary="Your notifications (newest first)")
async def inbox(response: Response, unread_only: bool = False, limit: int = Query(default=20, ge=1, le=50),
                offset: int = Query(default=0, ge=0, le=10_000), principal: Principal = Depends(own)):
    rows, total, unread = await _call(repo.inbox(principal.account_pk, unread_only, limit, offset))
    response.headers["X-Total-Count"] = str(total)
    return {"items": [_n(r) for r in rows], "total": total, "unread": unread}


@router.post("/farmers/me/notifications/{notification_id}/read", status_code=204, summary="Mark one as read")
async def read_one(notification_id: Annotated[int, Path(ge=1, le=2**62)], principal: Principal = Depends(own)):
    if not await _call(repo.mark_read(principal.account_pk, notification_id)):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Notification not found."})


@router.post("/farmers/me/notifications/read-all", summary="Mark all as read")
async def read_all(principal: Principal = Depends(own)):
    return {"marked": await _call(repo.mark_all_read(principal.account_pk))}


# ─── preferences ──────────────────────────────────────────────────────────────

class PreferencesUpdate(BaseModel):
    model_config = {"extra": "forbid"}

    in_app: Optional[StrictBool] = None
    email: Optional[StrictBool] = None
    sms: Optional[StrictBool] = None
    consequential_only: Optional[StrictBool] = None
    sms_consent: StrictBool = False          # must be true (with the shown consent text) to turn SMS on


@router.get("/farmers/me/notification-preferences", summary="Channels and what is available")
async def get_prefs(principal: Principal = Depends(own)):
    return await _call(svc.get_preferences(principal.account_pk))


@router.put("/farmers/me/notification-preferences", summary="Change channels (SMS needs consent)")
async def put_prefs(req: PreferencesUpdate, principal: Principal = Depends(own)):
    changes = {k: getattr(req, k) for k in ("in_app", "email", "sms", "consequential_only")
               if k in req.model_fields_set and getattr(req, k) is not None}
    if not changes:
        raise HTTPException(status_code=422, detail={"code": "NOTHING_TO_UPDATE", "message": "Nothing to update."})
    return await _call(svc.update_preferences(principal.account_pk, principal, changes, req.sms_consent))


# ─── subscriptions ────────────────────────────────────────────────────────────

@router.get("/farmers/me/subscriptions", summary="Schemes you follow")
async def subscriptions(principal: Principal = Depends(own)):
    rows = await _call(repo.list_subscriptions(principal.account_pk))
    return [{"scheme_id": r["scheme_id"], "scheme_name": r["scheme_name"], "since": r["created_at"].isoformat()}
            for r in rows]


@router.put("/farmers/me/subscriptions/{scheme_id}", summary="Follow a scheme's updates")
async def follow(scheme_id: SchemeIdPath, response: Response, principal: Principal = Depends(own)):
    if await _call(repo.scheme_name(scheme_id)) is None:
        raise HTTPException(status_code=404, detail={"code": "SCHEME_NOT_FOUND", "message": "Scheme not found."})
    created = await _call(repo.subscribe(principal.account_pk, scheme_id))
    response.status_code = 201 if created else 200
    return {"scheme_id": scheme_id, "following": True, "created": created}


@router.delete("/farmers/me/subscriptions/{scheme_id}", status_code=204, summary="Stop following")
async def unfollow(scheme_id: SchemeIdPath, principal: Principal = Depends(own)):
    if not await _call(repo.unsubscribe(principal.account_pk, scheme_id)):
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "You don't follow this scheme."})


# ─── phone ────────────────────────────────────────────────────────────────────

class PhoneRequest(BaseModel):
    model_config = {"extra": "forbid"}
    phone: str = Field(min_length=10, max_length=20)


class CodeRequest(BaseModel):
    model_config = {"extra": "forbid"}
    code: str = Field(pattern=r"^\d{6}$")


@router.post("/farmers/me/phone", summary="Send a verification code to a phone number")
async def start_phone(req: PhoneRequest, principal: Principal = Depends(own)):
    _rate("phone_code_account", str(principal.account_pk), 3, 3600)
    _rate("phone_code_number", req.phone[-10:], 3, 3600)
    return await _call(svc.start_phone_verification(principal.account_pk, req.phone))


@router.post("/farmers/me/phone/verify", summary="Confirm the code")
async def verify_phone(req: CodeRequest, principal: Principal = Depends(own)):
    _rate("phone_verify", str(principal.account_pk), 10, 3600)
    return await _call(svc.confirm_phone(principal.account_pk, principal, req.code))


@router.delete("/farmers/me/phone", status_code=204, summary="Remove the phone number (also turns SMS off)")
async def delete_phone(principal: Principal = Depends(own)):
    await _call(repo.remove_phone(principal.account_pk))


# ─── public, self-authenticating ──────────────────────────────────────────────

class UnsubscribeRequest(BaseModel):
    model_config = {"extra": "forbid"}
    token: str = Field(min_length=10, max_length=300)


@router.post("/notifications/unsubscribe", summary="One-click unsubscribe (token from the e-mail)")
async def unsubscribe(req: UnsubscribeRequest, request: Request):
    _rate("unsubscribe_ip", request.client.host if request.client else "?", 30, 3600)
    parsed = svc.parse_unsubscribe_token(req.token)
    if not parsed:
        raise HTTPException(status_code=400, detail={"code": "BAD_TOKEN", "message": "This link is not valid."})
    pk = await _call(repo.account_pk_by_uuid(parsed[0]))
    if pk:
        field = parsed[1]
        await _call(repo.save_prefs(pk, {field: False, f"{field}_opted_out_at": datetime.now(timezone.utc)}))
        await audit_repository.record(Principal(role=None, label="unsubscribe-link", via="link", account_pk=pk),
                                      "NOTIFICATION_UNSUBSCRIBED", "account", parsed[0], {"channel": field})
    return {"unsubscribed": parsed[1]}            # same answer whether or not the account still exists


class SmsStatus(BaseModel):
    message_id: str = Field(max_length=120)
    status: Literal["delivered", "undelivered", "failed"]
    error: Optional[str] = Field(default=None, max_length=200)


@router.post("/notifications/sms-status", status_code=204, summary="SMS provider delivery report (signed)")
async def sms_status(request: Request, x_signature: Optional[str] = Header(default=None)):
    body = await request.body()
    if not channels.status_signature_valid(body, x_signature):
        raise HTTPException(status_code=403, detail={"code": "BAD_SIGNATURE", "message": "Invalid signature."})
    report = SmsStatus.model_validate_json(body)
    new = "DELIVERED" if report.status == "delivered" else "UNDELIVERED"
    from app.core.redaction import redact
    await _call(repo.provider_status(report.message_id, new, redact(report.error, 200) if report.error else None))
