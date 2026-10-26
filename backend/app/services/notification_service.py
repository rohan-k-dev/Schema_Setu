"""
Farmer notifications (docs/SCHEME_UPDATES.md): follow / unfollow schemes, channel
preferences with SMS consent and opt-out, phone verification, the in-app inbox,
one-click e-mail unsubscribe, and the delivery dispatcher with retries.

Channel rules (checked when a preference is set AND again at every send):
  in-app   always available; on by default.
  e-mail   off by default; needs a verified account e-mail and SMTP configured.
  SMS      off by default; needs a configured provider, a verified phone number and
           explicit consent (time + consent-text version recorded). Turning it off is an
           opt-out that takes effect for deliveries already queued.

Delivery: each (notification, channel) is delivered at most once. Failures are retried
with backoff up to NOTIFY_MAX_ATTEMPTS, then GAVE_UP; non-retryable failures (not
configured, opted out, unverified contact) are SKIPPED; a SENT delivery is never sent again.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.core.permissions import Principal
from app.core.redaction import redact
from app.core.security import _CSRF_KEY
from app.database.repositories import audit_repository as audit_repo
from app.database.repositories import notification_repository as repo
from app.services import notification_channels as channels

logger = get_logger(__name__)

BACKOFF_MINUTES = (1, 5, 30, 120, 360)
PHONE_CODE_MINUTES = 10
PHONE_CODE_ATTEMPTS = 5
SMS_CONSENT_TEXT = ("I agree to receive SMS from SchemeSetu about changes to schemes I saved or follow. "
                    "Standard SMS rates may apply. I can turn this off at any time in my notification settings.")
_PHONE = re.compile(r"^(?:\+?91[\s-]?)?([6-9]\d{9})$")


class NotifyRejected(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def normalize_phone(raw: str) -> str:
    m = _PHONE.match(re.sub(r"[\s()-]", "", raw or ""))
    if not m:
        raise NotifyRejected("BAD_PHONE", "Enter a 10-digit Indian mobile number.", 422)
    return f"+91{m.group(1)}"


# ─── preferences ──────────────────────────────────────────────────────────────

async def availability(pk: int) -> Dict[str, Any]:
    contact = await repo.account_contact(pk)
    return {
        "email_configured": channels.email_available(), "email_verified": bool(contact and contact["is_verified"]),
        "sms_available": channels.sms_available(),
        "phone": channels.mask_phone(contact["phone"]) if contact and contact["phone"] else None,
        "phone_verified": bool(contact and contact["phone_verified_at"]),
        "sms_consent_text": SMS_CONSENT_TEXT, "sms_consent_version": settings.SMS_CONSENT_VERSION,
    }


async def get_preferences(pk: int) -> Dict[str, Any]:
    prefs = await repo.get_prefs(pk)
    return {"preferences": _prefs_out(prefs), "channels": await availability(pk)}


def _prefs_out(p: dict) -> dict:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in p.items()}


async def update_preferences(pk: int, principal: Principal, changes: Dict[str, Any],
                             sms_consent: bool) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    avail = await availability(pk)
    write: Dict[str, Any] = {k: changes[k] for k in ("in_app", "consequential_only") if k in changes}
    if "email" in changes:
        if changes["email"] and not (avail["email_configured"] and avail["email_verified"]):
            raise NotifyRejected("EMAIL_UNAVAILABLE", "E-mail notifications aren't available: "
                                 + ("e-mail isn't set up on this server." if not avail["email_configured"]
                                    else "verify your e-mail address first."))
        write["email"] = changes["email"]
        write["email_opted_out_at"] = None if changes["email"] else now
    if "sms" in changes:
        if changes["sms"]:
            if not avail["sms_available"]:
                raise NotifyRejected("SMS_UNAVAILABLE", "SMS isn't available on this server.")
            if not avail["phone_verified"]:
                raise NotifyRejected("PHONE_NOT_VERIFIED", "Verify your phone number first.")
            if not sms_consent:
                raise NotifyRejected("CONSENT_REQUIRED", "Agree to the SMS consent text to turn SMS on.", 422)
            write.update(sms=True, sms_consent_at=now, sms_consent_version=settings.SMS_CONSENT_VERSION,
                         sms_opted_out_at=None)
        else:
            write.update(sms=False, sms_opted_out_at=now)
    prefs = await repo.save_prefs(pk, write)
    if "sms" in changes or "email" in changes:
        await audit_repo.record(principal, "NOTIFICATION_CONSENT", "account", principal.farmer_id,
                                {"sms": prefs["sms"], "email": prefs["email"],
                                 "sms_consent_version": prefs["sms_consent_version"]})
    return {"preferences": _prefs_out(prefs), "channels": avail}


# ─── phone verification ───────────────────────────────────────────────────────

def _code_hash(pk: int, code: str) -> str:
    return hmac.new(_CSRF_KEY, f"phone:{pk}:{code}".encode(), hashlib.sha256).hexdigest()


async def start_phone_verification(pk: int, raw_phone: str) -> Dict[str, Any]:
    if not channels.sms_available():
        raise NotifyRejected("SMS_UNAVAILABLE", "Phone verification needs SMS, which isn't available on this server.", 503)
    phone = normalize_phone(raw_phone)
    code = f"{secrets.randbelow(1_000_000):06d}"
    await repo.create_phone_code(pk, _code_hash(pk, code), phone,
                                 datetime.now(timezone.utc) + timedelta(minutes=PHONE_CODE_MINUTES))
    try:
        await channels.send_sms(phone, f"Your SchemeSetu verification code is {code}. It expires in "
                                       f"{PHONE_CODE_MINUTES} minutes. Don't share it.", f"otp-{pk}-{secrets.token_hex(6)}")
    except channels.ChannelError:
        raise NotifyRejected("SMS_FAILED", "We couldn't send the code. Please try again later.", 503)
    return {"sent_to": channels.mask_phone(phone), "expires_in_minutes": PHONE_CODE_MINUTES}


async def confirm_phone(pk: int, principal: Principal, code: str) -> Dict[str, Any]:
    try:
        result, phone = await repo.check_phone_code(pk, _code_hash(pk, code), PHONE_CODE_ATTEMPTS)
    except repo.PhoneInUse:
        raise NotifyRejected("PHONE_UNAVAILABLE", "This number can't be used. Try another number.")
    if result != "ok":
        msg = {"none": "No valid code: request a new one.", "locked": "Too many wrong codes: request a new one.",
               "wrong": "That code is not correct."}[result]
        raise NotifyRejected(f"CODE_{result.upper()}", msg, 400)
    await audit_repo.record(principal, "PHONE_VERIFIED", "account", principal.farmer_id)
    return {"phone": channels.mask_phone(phone), "phone_verified": True,
            "note": "Turn on SMS in your notification settings if you want SMS alerts."}


# ─── unsubscribe links (e-mail) ───────────────────────────────────────────────

_UNSUB_KEY = hashlib.sha256(b"unsubscribe:" + _CSRF_KEY).digest()


def unsubscribe_token(farmer_uuid: str, channel: str) -> str:
    payload = base64.urlsafe_b64encode(f"{farmer_uuid}:{channel}".encode()).decode().rstrip("=")
    sig = hmac.new(_UNSUB_KEY, payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}.{sig}"


def parse_unsubscribe_token(token: str) -> Optional[tuple[str, str]]:
    try:
        payload, sig = token.split(".", 1)
        if not hmac.compare_digest(hmac.new(_UNSUB_KEY, payload.encode(), hashlib.sha256).hexdigest()[:32], sig):
            return None
        farmer_uuid, channel = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode().split(":")
        return (farmer_uuid, channel) if channel in ("email", "sms") else None
    except Exception:
        return None


# ─── dispatch ─────────────────────────────────────────────────────────────────

def _next_attempt(attempts: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=BACKOFF_MINUTES[min(attempts, len(BACKOFF_MINUTES)) - 1])


async def _deliver(d: dict) -> None:
    prefs = await repo.get_prefs(d["farmer_id"])
    try:
        if not d["is_active"]:
            raise channels.ChannelError("Account deactivated.", retryable=False)
        if d["channel"] == "EMAIL":
            if not prefs["email"]:
                raise channels.ChannelError("Opted out of e-mail.", retryable=False)
            if not d["is_verified"]:
                raise channels.ChannelError("E-mail address not verified.", retryable=False)
            from app.core.config import settings as s
            link = f"{s.FRONTEND_BASE_URL.rstrip('/')}/unsubscribe?token={unsubscribe_token(d['account_uuid'], 'email')}"
            mid = await channels.send_email(
                d["email"], f"SchemeSetu: {d['title']}",
                f"{d['body']}\n\nStop these e-mails: {link}\nOr change it in your notification settings.", link)
        else:
            if not prefs["sms"] or not prefs["sms_consent_at"]:
                raise channels.ChannelError("No SMS consent / opted out.", retryable=False)
            if not d["phone"] or not d["phone_verified_at"]:
                raise channels.ChannelError("Phone number not verified.", retryable=False)
            text = f"SchemeSetu: {d['title'][:90]}. Open SchemeSetu for details. Turn off SMS in settings."
            mid = await channels.send_sms(d["phone"], text, f"delivery-{d['id']}")
        await repo.finish(d["id"], "SENT", provider_message_id=mid)
    except channels.ChannelError as exc:
        if not exc.retryable:
            await repo.finish(d["id"], "SKIPPED", error=redact(str(exc), 300))
        elif d["attempts"] >= settings.NOTIFY_MAX_ATTEMPTS:
            await repo.finish(d["id"], "GAVE_UP", error=redact(str(exc), 300))
        else:
            await repo.finish(d["id"], "FAILED", error=redact(str(exc), 300),
                              next_attempt_at=_next_attempt(d["attempts"]))


async def dispatch_due(limit: int = 100) -> Dict[str, int]:
    """Send every due delivery once (claimed atomically); returns how many were handled."""
    stuck = await repo.abandon_stuck()
    handled = 0
    while True:
        batch = await repo.claim_due(min(limit - handled, 50))
        if not batch:
            break
        for d in batch:
            contact = await repo.account_contact(d["farmer_id"])
            d["account_uuid"] = contact["farmer_id"] if contact else ""
            try:
                await _deliver(d)
            except Exception as exc:            # never leave a claimed delivery in SENDING
                logger.error(f"Delivery {d['id']} crashed: {type(exc).__name__}")
                await repo.finish(d["id"], "FAILED", error=f"Internal error ({type(exc).__name__})",
                                  next_attempt_at=_next_attempt(d["attempts"]))
            handled += 1
        if handled >= limit:
            break
    return {"handled": handled, "abandoned_stuck": stuck}


async def dispatch_loop(interval: int) -> None:
    """Retry due deliveries in the background (one backend process; docs/SCHEME_UPDATES.md)."""
    while True:
        await asyncio.sleep(interval)
        try:
            await dispatch_due()
        except Exception as exc:
            logger.error(f"Notification dispatch failed: {type(exc).__name__}")
