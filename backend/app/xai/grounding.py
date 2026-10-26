"""
Grounding checks for natural-language text (Phase 7, BUG-013 / BUG-014).

Used to reject explanations or LLM replies that contain claims not backed by
the deterministic evidence: eligibility claims that contradict the engine,
numbers or URLs that are not in the evidence, criteria for fields that were
never evaluated, and scheme names that were never retrieved.
"""

import re
from typing import Any, Iterable, List, Set

URL_RE = re.compile(r"https?://[^\s)\]>\"'<,]+")
NUM_RE = re.compile(r"(?<![\w.])\d+(?:,\d{2,3})*(?:\.\d+)?")
MONEY_RE = re.compile(
    r"(?:₹|rs\.?|inr|rupees?)\s*(\d+(?:,\d{2,3})*(?:\.\d+)?)"
    r"|(\d+(?:,\d{2,3})*(?:\.\d+)?)\s*(?:/-)?\s*(?:rupees|rs\b|inr)",
    re.IGNORECASE,
)
AFFIRMATIVE_ELIGIBLE_RE = re.compile(
    r"\b(?:you\s+are|you're|youre|you\s+will\s+be|are|is|qualif(?:y|ies)\s+as)\s+"
    r"(?:now\s+|definitely\s+|fully\s+|also\s+)?eligible\b"
    r"|\byou\s+(?:definitely\s+|also\s+)?qualify\b",
    re.IGNORECASE,
)
NEGATED_RE = re.compile(r"\b(?:not|n't|never|ineligible)\b", re.IGNORECASE)
NOT_ELIGIBLE_RE = re.compile(r"\b(?:not\s+eligible|ineligible|do(?:es)?\s+not\s+qualify)\b", re.IGNORECASE)
GLOBAL_CLAIM_RE = re.compile(r"\beligible\s+for\s+(?:all|every|each)\b", re.IGNORECASE)


def _to_float(token: str):
    try:
        return round(float(token.replace(",", "")), 6)
    except ValueError:
        return None


def numbers_in(text: str) -> Set[float]:
    return {n for n in (_to_float(m) for m in NUM_RE.findall(text or "")) if n is not None}


def money_amounts_in(text: str) -> Set[float]:
    out = set()
    for a, b in MONEY_RE.findall(text or ""):
        n = _to_float(a or b)
        if n is not None:
            out.add(n)
    return out


def urls_in(text: str) -> Set[str]:
    return {u.rstrip(".") for u in URL_RE.findall(text or "")}


def numbers_from_values(values: Iterable[Any]) -> Set[float]:
    """All numbers contained in arbitrary nested evidence values."""
    out: Set[float] = set()
    stack = list(values)
    while stack:
        v = stack.pop()
        if v is None or isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            out.add(round(float(v), 6))
        elif isinstance(v, str):
            out |= numbers_in(v)
        elif isinstance(v, dict):
            stack.extend(v.values())
        elif isinstance(v, (list, tuple, set)):
            stack.extend(v)
    return out


def strings_from_values(values: Iterable[Any]) -> List[str]:
    out: List[str] = []
    stack = list(values)
    while stack:
        v = stack.pop()
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, dict):
            stack.extend(v.values())
        elif isinstance(v, (list, tuple, set)):
            stack.extend(v)
    return out


def sentences(text: str) -> List[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n+", text or "") if s.strip()]


def affirms_eligibility(sentence: str) -> bool:
    """True when a sentence positively claims eligibility (not negated)."""
    if not AFFIRMATIVE_ELIGIBLE_RE.search(sentence):
        return False
    return not NEGATED_RE.search(sentence)
