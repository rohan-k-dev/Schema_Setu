"""
Field-level verification of stored scheme records against live official pages.

For each field: CONFIRMED (the live page states the same), CONFLICT (it states something
different — both values are kept and shown; the stored record and its rules are NOT changed),
LIVE_ONLY (stated live, not stored), STORED_ONLY (stored, not found on any page checked now —
i.e. not verified during this request), or absent. Comparisons are deterministic: numbers for
amounts, overlap of key terms for documents, hosts for links, keywords for open / closed.
Eligibility text is shown as evidence only; it is never compared or turned into rules here.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from app.live.extractor import Extraction, _amounts
from app.live.sources import host_of

CONFIRMED, CONFLICT, LIVE_ONLY, STORED_ONLY, EVIDENCE_ONLY = (
    "CONFIRMED", "CONFLICT", "LIVE_ONLY", "STORED_ONLY", "EVIDENCE_ONLY")

_DOC_TERMS = ("aadhaar", "land", "bank", "passbook", "photo", "ration", "income", "caste", "domicile", "residence",
              "mobile", "pan", "voter", "kisan credit", "sowing", "lease", "bpl", "age", "birth", "account")


def _terms(items: Optional[List[str]]) -> Set[str]:
    text = " ".join(items or []).lower()
    return {t for t in _DOC_TERMS if re.search(rf"\b{re.escape(t)}", text)}


def _stored_amounts(benefits: Optional[str]) -> Set[float]:
    return {float(a["amount"]) for a in _amounts(benefits or "")} if benefits else set()


def verify(stored: Dict[str, Any], ex: Extraction, source_url: str) -> Dict[str, Dict[str, Any]]:
    """
    stored: {"benefits": str, "documents": [..], "official_url": str, "status": "ACTIVE"/..., "name": str,
             "eligibility_summary": str}
    Returns {field: {"status": ..., "live": ..., "stored": ..., "evidence": ..., "source_url": ...}}.
    """
    out: Dict[str, Dict[str, Any]] = {}
    f = ex.fields

    def put(name, status, live=None, st=None, evidence=None):
        out[name] = {"status": status, "live": live, "stored": st, "evidence": evidence, "source_url": source_url}

    # benefit amounts
    s_amt = _stored_amounts(stored.get("benefits"))
    if "benefit_amounts" in f:
        l_amt = {float(a["amount"]) for a in f["benefit_amounts"].value}
        if s_amt:
            put("benefit_amounts", CONFIRMED if s_amt & l_amt else CONFLICT,
                sorted(l_amt), sorted(s_amt), f["benefit_amounts"].evidence)
        else:
            put("benefit_amounts", LIVE_ONLY, sorted(l_amt), None, f["benefit_amounts"].evidence)
    elif s_amt:
        put("benefit_amounts", STORED_ONLY, None, sorted(s_amt))

    # documents
    s_docs = stored.get("documents") or []
    if "documents" in f:
        lt, st = _terms(f["documents"].value), _terms(s_docs)
        if s_docs and lt and st:
            put("documents", CONFIRMED if lt & st else CONFLICT, f["documents"].value, s_docs, f["documents"].evidence)
        elif s_docs:                                 # nothing comparable on one side: show, don't judge
            put("documents", EVIDENCE_ONLY, f["documents"].value, s_docs, f["documents"].evidence)
        else:
            put("documents", LIVE_ONLY, f["documents"].value, None, f["documents"].evidence)
    elif s_docs:
        put("documents", STORED_ONLY, None, s_docs)

    # application link: same official host as the stored link?
    s_url = stored.get("official_url")
    if "application_url" in f:
        live_host = host_of(f["application_url"].value)
        if s_url:
            put("application_url", CONFIRMED if live_host and live_host == host_of(s_url) else LIVE_ONLY,
                f["application_url"].value, s_url, f["application_url"].evidence)
        else:
            put("application_url", LIVE_ONLY, f["application_url"].value, None, f["application_url"].evidence)

    # open / closed: a stored ACTIVE scheme whose official page says applications are closed is a conflict
    if "application_status" in f:
        live = f["application_status"].value
        s_status = (stored.get("status") or "").upper()
        if s_status:
            same = (live == "OPEN" and s_status == "ACTIVE") or (live == "CLOSED" and s_status != "ACTIVE")
            put("application_status", CONFIRMED if same else CONFLICT, live, s_status, f["application_status"].evidence)
        else:
            put("application_status", LIVE_ONLY, live, None, f["application_status"].evidence)

    for name in ("important_dates", "ministry", "income_requirement", "land_requirement", "exclusions"):
        if name in f:
            put(name, LIVE_ONLY, f[name].value, None, f[name].evidence)
    for name in ("eligibility", "benefits", "application_process"):
        if name in f:                               # shown for people to read; not compared automatically
            put(name, EVIDENCE_ONLY, f[name].value, stored.get("eligibility_summary") if name == "eligibility" else None,
                f[name].evidence)
    return out
