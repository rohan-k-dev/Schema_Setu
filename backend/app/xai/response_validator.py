"""
LLM reply validation for the response formatter (Phase 7 §99–§105, BUG-013).

The LLM only rephrases structured evidence. Before its text reaches the user
it is checked against the structured response data; any unsupported content
causes the deterministic, evidence-based reply to be used instead.
"""

import re
from typing import Any, Dict, List, Tuple

from app.xai.grounding import (
    sentences, affirms_eligibility, GLOBAL_CLAIM_RE, money_amounts_in, urls_in,
    numbers_from_values, strings_from_values,
)

_BOLD_RE = re.compile(r"\*\*([^*]{3,120})\*\*")
_STOPWORDS = {"the", "of", "for", "and", "scheme", "yojana", "mission", "pradhan", "mantri", "national",
              "programme", "program", "pariyojana", "pm", "-", "&", "a", "in", "on"}


def _tokens(text: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t not in _STOPWORDS}


def _names_for(scheme: Dict[str, Any]) -> List[str]:
    names = [scheme.get("name") or "", scheme.get("scheme_id") or ""]
    sid = (scheme.get("scheme_id") or "").replace("_", " ")
    names.append(sid)
    m = re.search(r"\(([A-Z][A-Za-z\-]{2,})\)", scheme.get("name") or "")
    if m:
        names.append(m.group(1))
    return [n for n in names if n]


def _mentions(sentence: str, scheme: Dict[str, Any]) -> bool:
    low = sentence.lower()
    for n in _names_for(scheme):
        if len(n) >= 3 and n.lower() in low:
            return True
    name_tokens = _tokens(scheme.get("name") or "")
    return bool(name_tokens) and len(name_tokens & _tokens(sentence)) >= max(2, int(0.6 * len(name_tokens)))


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _known_scheme(bold: str, schemes: List[Dict[str, Any]]) -> bool:
    bt = _tokens(bold)
    if not bt:
        return True
    nb = _norm(bold)
    for s in schemes:
        for n in _names_for(s):
            nn = _norm(n)
            if len(nn) >= 3 and (nn in nb or nb in nn):
                return True
        nt = _tokens(s.get("name") or "")
        if nt and len(bt & nt) >= max(2, round(0.6 * len(bt))):
            return True
    return False


def validate_llm_response(text: str, schemes: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    """
    Returns (is_valid, reasons). schemes = the structured response_schemes,
    whose eligibility_status values are authoritative.
    """
    reasons: List[str] = []
    if not text or not text.strip():
        return False, ["empty reply"]

    statuses = {s.get("scheme_id"): s.get("eligibility_status") for s in schemes}
    not_eligible = [s for s in schemes if s.get("eligibility_status") != "ELIGIBLE"]

    # 1. Eligibility claims must match the engine (§100, §101)
    for sent in sentences(text):
        if not affirms_eligibility(sent):
            continue
        if GLOBAL_CLAIM_RE.search(sent) and not_eligible:
            reasons.append("claims eligibility for all schemes")
        for s in not_eligible:
            if _mentions(sent, s):
                reasons.append(f"claims eligibility for {s.get('scheme_id')} "
                               f"(engine: {statuses.get(s.get('scheme_id'))})")

    # 2. URLs must come from the evidence (§103)
    evidence_strings = strings_from_values(schemes)
    evidence_urls = set()
    for st in evidence_strings:
        evidence_urls |= urls_in(st)
        if st.startswith("http"):
            evidence_urls.add(st.rstrip("."))
    for u in urls_in(text):
        if u not in evidence_urls and u.rstrip("/") not in {e.rstrip("/") for e in evidence_urls}:
            reasons.append(f"unsupported URL {u}")

    # 3. Money amounts must come from the evidence (§104)
    evidence_numbers = numbers_from_values(schemes)
    for amount in money_amounts_in(text):
        if amount not in evidence_numbers:
            reasons.append(f"unsupported amount {amount:g}")

    # 4. Scheme names must be retrieved candidates (§105)
    for bold in _BOLD_RE.findall(text):
        # Section headings ("**Schemes that need more information**") are not scheme names;
        # real scheme names are singular ("... Scheme", "... Yojana"). Found in the first live run.
        if re.search(r"\bschemes\b", bold, re.I):
            continue
        if re.search(r"(yojana|scheme|mission|pariyojana|abhiyan|programme|card|nidhi|bima)", bold, re.I) \
                and not _known_scheme(bold, schemes):
            reasons.append(f"unknown scheme name '{bold}'")

    return (not reasons), reasons
