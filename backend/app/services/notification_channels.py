"""
Delivery channels for scheme-update notifications (docs/SCHEME_UPDATES.md).

E-mail: SMTP only. Without SMTP_HOST the channel is "not configured" and deliveries
are marked SKIPPED (never SENT): unlike account e-mails, nothing is faked to the log.

SMS: only through a configured provider:
  SMS_PROVIDER=http   POST {to, message, sender, idempotency_key, status_callback} to SMS_HTTP_URL with
                      "Authorization: Bearer SMS_HTTP_TOKEN"; the provider answers {"message_id"}.
                      Delivery reports come back to POST /notifications/sms-status, signed with
                      HMAC-SHA256(SMS_STATUS_SECRET, body) in X-Signature.
  SMS_PROVIDER=log    development only: writes a masked line to the log; refused in production.

Every send raises ChannelError on failure (retryable or not) so a failure is never
recorded as a delivery.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import smtplib
import uuid
from email.message import EmailMessage
from typing import Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class ChannelError(Exception):
    def __init__(self, message: str, retryable: bool = True):
        self.retryable = retryable
        super().__init__(message)


def mask_phone(phone: Optional[str]) -> str:
    return f"***{phone[-3:]}" if phone and len(phone) > 3 else "***"


# ─── e-mail ───────────────────────────────────────────────────────────────────

def email_available() -> bool:
    return bool(settings.SMTP_HOST)


def _smtp_send(to: str, subject: str, body: str, message_id: str, unsubscribe_url: Optional[str]) -> None:
    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    if unsubscribe_url:
        msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    msg.set_content(body)
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
        if settings.SMTP_STARTTLS:
            smtp.starttls()
        if settings.SMTP_USERNAME:
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD or "")
        smtp.send_message(msg)


async def send_email(to: str, subject: str, body: str, unsubscribe_url: Optional[str] = None) -> str:
    """Returns the Message-ID used; raises ChannelError."""
    if not email_available():
        raise ChannelError("E-mail is not configured (SMTP_HOST).", retryable=False)
    message_id = f"<{uuid.uuid4().hex}@schemesetu>"
    try:
        await asyncio.to_thread(_smtp_send, to, subject, body, message_id, unsubscribe_url)
    except smtplib.SMTPRecipientsRefused as exc:
        raise ChannelError(f"Recipient refused ({type(exc).__name__})", retryable=False)
    except Exception as exc:
        raise ChannelError(f"SMTP error ({type(exc).__name__})")
    return message_id


# ─── SMS ──────────────────────────────────────────────────────────────────────

def sms_available() -> bool:
    if settings.SMS_PROVIDER == "http":
        return bool(settings.SMS_HTTP_URL and settings.SMS_HTTP_TOKEN)
    if settings.SMS_PROVIDER == "log":
        return settings.ENVIRONMENT != "production"
    return False


def sms_status_callback_url() -> str:
    return f"{settings.API_BASE_URL.rstrip('/')}/notifications/sms-status"


async def send_sms(to: str, text: str, idempotency_key: str) -> str:
    """Returns the provider's message id; raises ChannelError."""
    if not sms_available():
        raise ChannelError("No SMS provider is configured.", retryable=False)
    if settings.SMS_PROVIDER == "log":
        logger.warning(f"DEV SMS (log provider) to {mask_phone(to)}: {text}")
        return f"log-{idempotency_key}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                settings.SMS_HTTP_URL,
                headers={"Authorization": f"Bearer {settings.SMS_HTTP_TOKEN}", "Idempotency-Key": idempotency_key},
                json={"to": to, "message": text, "sender": settings.SMS_SENDER_ID,
                      "idempotency_key": idempotency_key, "status_callback": sms_status_callback_url()})
    except httpx.HTTPError as exc:
        raise ChannelError(f"SMS provider unreachable ({type(exc).__name__})")
    if r.status_code >= 500 or r.status_code == 429:
        raise ChannelError(f"SMS provider error HTTP {r.status_code}")
    if r.status_code >= 400:
        raise ChannelError(f"SMS rejected by provider (HTTP {r.status_code})", retryable=False)
    try:
        return str(r.json()["message_id"])[:120]
    except Exception:
        raise ChannelError("SMS provider sent no message id", retryable=False)


def status_signature(body: bytes) -> str:
    return hmac.new((settings.SMS_STATUS_SECRET or "").encode(), body, hashlib.sha256).hexdigest()


def status_signature_valid(body: bytes, signature: Optional[str]) -> bool:
    if not settings.SMS_STATUS_SECRET or not signature:
        return False
    return hmac.compare_digest(status_signature(body), signature)
