"""
Outgoing e-mail for password reset and account notices.

With SMTP_HOST configured, mail is sent over SMTP (STARTTLS by default).
Without it, in non-production environments the message — including its link —
is written to the backend log so the flows can be tested locally
(`docker compose logs backend`). In production without SMTP nothing is sent and
an error is logged without the link (tokens never reach production logs).
"""

from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


def _send_smtp(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as smtp:
        if settings.SMTP_STARTTLS:
            smtp.starttls()
        if settings.SMTP_USERNAME:
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD or "")
        smtp.send_message(msg)


async def send_email(to: str, subject: str, body: str) -> bool:
    """Send one e-mail. Never raises: account flows must not reveal delivery failures."""
    if settings.SMTP_HOST:
        try:
            await asyncio.to_thread(_send_smtp, to, subject, body)
            logger.info(f"E-mail sent to {mask_email(to)}: {subject}")
            return True
        except Exception as exc:
            logger.error(f"E-mail to {mask_email(to)} failed: {type(exc).__name__}")
            return False
    if settings.ENVIRONMENT == "production":
        logger.error(f"SMTP_HOST is not configured; e-mail '{subject}' to {mask_email(to)} not sent")
        return False
    logger.warning(
        f"DEV E-MAIL (SMTP not configured) to {mask_email(to)}\n"
        f"  Subject: {subject}\n  {body.strip().replace(chr(10), chr(10) + '  ')}"
    )
    return True


def _link(path: str, token: str) -> str:
    return f"{settings.FRONTEND_BASE_URL.rstrip('/')}{path}?token={token}"


async def send_account_exists_email(to: str) -> bool:
    return await send_email(
        to, "SchemeSetu sign-up attempt",
        "Someone tried to create a SchemeSetu account with this e-mail address, "
        "but an account already exists.\n\nIf this was you, sign in instead, or reset your password:\n"
        f"{settings.FRONTEND_BASE_URL.rstrip('/')}/auth\n\nIf it wasn't you, you can ignore this e-mail.",
    )


async def send_password_reset_email(to: str, token: str) -> bool:
    return await send_email(
        to, "Reset your SchemeSetu password",
        f"Open this link to choose a new password:\n{_link('/reset-password', token)}\n\n"
        f"The link works once and expires in {settings.PASSWORD_RESET_EXPIRE_MINUTES} minutes. "
        f"If you did not ask for this, ignore this e-mail — your password stays the same.",
    )


async def send_password_changed_email(to: str) -> bool:
    return await send_email(
        to, "Your SchemeSetu password was changed",
        "Your password was changed and every device was signed out.\n\n"
        "If you did not do this, reset your password now:\n"
        f"{settings.FRONTEND_BASE_URL.rstrip('/')}/auth",
    )
