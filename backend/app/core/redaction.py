"""
Redaction for anything an administrator can read back: audit details, captured
errors, job results (docs/ADMIN_OPERATIONS.md).

Removes passwords, API keys, tokens, cookies, connection-string credentials,
e-mail addresses, phone and Aadhaar-like numbers. Applied when the text is stored,
so nothing sensitive is kept even if it reached a log message by mistake.
"""

from __future__ import annotations

import re
from typing import Any

MAX_TEXT = 500

# key names whose values are never kept
SENSITIVE_KEYS = re.compile(
    r"pass(word|wd)?|secret|token|api[_-]?key|authorization|cookie|session|csrf|otp|"
    r"aadhaar|aadhar|phone|mobile|email|e_mail|bank|account_number|ifsc|profile", re.I)

_PATTERNS = [
    (re.compile(r"(\w+://)[^/\s:@]+:[^/\s@]+@"), r"\1***:***@"),                      # URL credentials
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._\-~+/]+=*"), r"\1 [redacted]"),
    (re.compile(r"(?i)\b(pass(?:word|wd)?|secret|token|api[_-]?key|authorization|cookie|session|csrf)"
                r"(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;&]+)"), r"\1\2[redacted]"),
    (re.compile(r"\b(gsk|tvly|sk|pk)[-_][A-Za-z0-9\-_]{10,}"), "[redacted-key]"),      # provider-style keys
    # long opaque tokens (session cookies, reset links); hex hashes and UUIDs are not secrets
    (re.compile(r"[A-Za-z0-9_\-]{32,}"),
     lambda m: m.group(0) if re.fullmatch(r"[0-9a-fA-F\-]+", m.group(0)) else "[redacted-token]"),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}\b"), "[number]"),                        # Aadhaar-like
    (re.compile(r"(?<!\d)(?:\+?91[ -]?)?[6-9]\d{9}(?!\d)"), "[phone]"),
]


def redact(text: Any, limit: int = MAX_TEXT) -> str:
    s = "" if text is None else str(text)
    for pattern, repl in _PATTERNS:
        s = pattern.sub(repl, s)
    s = "".join(ch if ch.isprintable() or ch in "\n\t" else "?" for ch in s)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def sanitize(value: Any, depth: int = 0) -> Any:
    """Recursively drop sensitive keys and redact strings in a JSON-like value (bounded size)."""
    if depth > 4:
        return "[truncated]"
    if isinstance(value, dict):
        return {str(k)[:60]: ("[redacted]" if SENSITIVE_KEYS.search(str(k)) else sanitize(v, depth + 1))
                for k, v in list(value.items())[:50]}
    if isinstance(value, (list, tuple)):
        return [sanitize(v, depth + 1) for v in list(value)[:50]]
    if isinstance(value, str):
        return redact(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact(value)
