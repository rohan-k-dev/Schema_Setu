"""
Recent operational errors for the admin dashboard (docs/ADMIN_OPERATIONS.md).

A logging handler keeps the newest ERROR / CRITICAL records of this process in a
bounded in-memory buffer — redacted (app.core.redaction) and tagged with the request's
correlation id. It is a convenience view, not the system of record: the full server
log remains the source, and the buffer is per process and empty after a restart.
"""

from __future__ import annotations

import itertools
import logging
import threading
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from app.core import request_context
from app.core.redaction import redact

CAPACITY = 500


class ErrorBuffer(logging.Handler):
    def __init__(self, capacity: int = CAPACITY):
        super().__init__(level=logging.ERROR)
        self._rows: deque = deque(maxlen=capacity)
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            exc_type = record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else None
            row = {
                "id": next(self._ids),
                "at": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name[:100],
                "message": redact(record.getMessage()),
                "exception_type": exc_type,
                "correlation_id": request_context.current(),
            }
            with self._lock:
                self._rows.append(row)
        except Exception:          # a logging handler must never raise
            pass

    def page(self, limit: int, offset: int) -> Tuple[List[dict], int]:
        with self._lock:
            rows = list(reversed(self._rows))
        return rows[offset:offset + limit], len(rows)

    def count_since(self, since: datetime) -> int:
        cutoff = since.isoformat()
        with self._lock:
            return sum(1 for r in self._rows if r["at"] >= cutoff)

    def clear(self) -> None:
        with self._lock:
            self._rows.clear()


buffer = ErrorBuffer()


def install() -> None:
    root = logging.getLogger()
    if buffer not in root.handlers:
        root.addHandler(buffer)


def last_24h() -> int:
    return buffer.count_since(datetime.now(timezone.utc) - timedelta(hours=24))


def latest(n: int = 5) -> List[dict]:
    return buffer.page(n, 0)[0]


def find(correlation_id: Optional[str]) -> List[dict]:
    rows, _ = buffer.page(CAPACITY, 0)
    return [r for r in rows if correlation_id and r["correlation_id"] == correlation_id]
