"""
Correlation ids (docs/ADMIN_OPERATIONS.md).

Every HTTP request gets an id: the caller's ``X-Request-ID`` if it is a safe token,
otherwise a new random one. It is returned in the ``X-Request-ID`` response header and
attached to audit events, captured errors and admin jobs, so one action can be followed
through the audit log, the error list and the server log.
"""

from __future__ import annotations

import re
import uuid
from contextvars import ContextVar
from typing import Optional

HEADER = "X-Request-ID"
_SAFE = re.compile(r"^[A-Za-z0-9._\-]{8,64}$")
_current: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


def new_id() -> str:
    return uuid.uuid4().hex


def accept(incoming: Optional[str]) -> str:
    """The caller's id if it is a safe token (no spaces, no control characters), else a new one."""
    return incoming if incoming and _SAFE.match(incoming) else new_id()


def current() -> Optional[str]:
    return _current.get()


def bind(correlation_id: Optional[str]):
    """Set the id for the current context (returns a token for reset())."""
    return _current.set(correlation_id)


def reset(token) -> None:
    _current.reset(token)


class CorrelationIdMiddleware:
    """Pure ASGI middleware (keeps streaming / background tasks working)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        incoming = None
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                incoming = value.decode("latin-1")
                break
        cid = accept(incoming)
        token = bind(cid)

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append((b"x-request-id", cid.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            reset(token)
