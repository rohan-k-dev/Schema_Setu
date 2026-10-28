"""
Meaningful-change detection between a candidate (newly scraped, normalised) corpus
and the last verified corpus (docs/SCHEME_UPDATES.md). Pure functions, no I/O.

Both sides are reduced to a canonical form per category before comparing, so
re-formatting is not reported as a change: whitespace, case, quotes and dashes,
list order, duplicate entries, "Rs. 6,000" vs "₹6000", 2 vs "2" vs 2.0, URL
trailing slashes / fragments / tracking parameters / http vs https, an empty state
list vs "all states", and provenance-only differences (retrieval dates, content
hashes, source text) are all ignored.

Tracked categories: eligibility criteria, benefits, state applicability, required
documents, application steps, URLs, active / inactive status — plus schemes that
are new in, or missing from, the candidate.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

CONSEQUENTIAL = {"ELIGIBILITY", "BENEFITS", "STATES", "STATUS", "NEW_SCHEME", "MISSING_FROM_SOURCE"}
CATEGORY_FIELDS = {
    "ELIGIBILITY": ("eligibility_rules",),
    "BENEFITS": ("benefits",),
    "STATES": ("applicable_states",),
    "DOCUMENTS": ("required_documents",),
    "STEPS": ("application_steps",),
    "URLS": ("official_url", "application_url"),
    "STATUS": ("status",),
}
LABEL = {
    "ELIGIBILITY": "Eligibility rules changed",
    "BENEFITS": "Benefits changed",
    "STATES": "The states where the scheme applies changed",
    "DOCUMENTS": "Required documents changed",
    "STEPS": "Application steps changed",
    "URLS": "Official / application links changed",
    "STATUS": "The scheme's status changed",
    "NEW_SCHEME": "New scheme found",
    "MISSING_FROM_SOURCE": "Scheme not found in the new source data",
}
# Batch-level sanity limits: beyond these the scrape itself is suspect (broken page, layout change).
SUSPICIOUS_MISSING_SHARE = 0.2
SUSPICIOUS_CHANGED_SHARE = 0.5

_TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|ref$|source$)", re.I)


# ─── canonical forms ──────────────────────────────────────────────────────────

def _v(x):
    return x.get("value") if isinstance(x, dict) and "value" in x else x


def text(s: Any) -> str:
    if s is None:
        return ""
    t = unicodedata.normalize("NFKC", str(s))
    t = t.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    t = re.sub(r"[‐-―]", "-", t)
    t = re.sub(r"\s+", " ", t).strip().casefold()
    return t.rstrip(" .;:,")


def number(x: Any) -> Any:
    """2, "2", 2.0, "2.00" → "2"; "Rs. 6,000" / "₹6000" → "6000"; other text → canonical text."""
    if isinstance(x, bool) or x is None:
        return x
    if isinstance(x, (int, float)):
        return format(float(x), "g")
    s = text(x)
    s2 = re.sub(r"(rs\.?|inr|₹|rupees?)", "", s).replace(",", "").strip()
    try:
        return format(float(s2), "g")
    except ValueError:
        # amounts in words: currency spelling, digit grouping and punctuation are formatting
        s = re.sub(r"(?<=\d),(?=\d)", "", re.sub(r"(rs\.?|₹|inr)\s*", "rs ", s))
        return re.sub(r"\s+", " ", re.sub(r"[^\w.\s]|(?<!\d)\.|\.(?!\d)", " ", s)).strip()


def url(u: Any) -> Optional[str]:
    if not u or not str(u).strip():
        return None
    try:
        p = urlsplit(str(u).strip())
    except ValueError:
        return text(u)
    host = (p.hostname or "").lower().removeprefix("www.")
    path = re.sub(r"/+$", "", p.path) or ""
    query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query) if not _TRACKING.match(k)))
    return urlunsplit(("", host, path, query, ""))          # scheme (http/https) and fragment dropped


def _value(v: Any) -> Any:
    if isinstance(v, (list, tuple, set)):
        return sorted({json.dumps(_value(x), sort_keys=True) for x in v})
    if isinstance(v, bool) or v is None:
        return v
    n = number(v)
    return n


def _rule(r: dict) -> Tuple:
    return (text(r.get("field")), text(_v(r.get("operator"))).upper(), json.dumps(_value(r.get("value")), sort_keys=True),
            text(_v(r.get("logical_group")) or "AND").upper(), bool(r.get("required", True)),
            text(r.get("unit")).rstrip("s"))


def _benefit(b: dict) -> Tuple:
    return (text(_v(b.get("type"))), number(b.get("amount")) if b.get("amount") else "", text(b.get("frequency")),
            text(b.get("condition")))


def _states(states: Optional[Sequence[str]]) -> Optional[List[str]]:
    from app.ingestion.normalizer import normalize_states
    if not states:
        return None                                        # None and [] both mean "all states"
    return sorted(set(normalize_states(list(states)) or [text(s) for s in states]))


def canonical(scheme: dict) -> Dict[str, Any]:
    return {
        "ELIGIBILITY": sorted(set(_rule(r) for r in scheme.get("eligibility_rules") or [])),
        "BENEFITS": sorted(set(_benefit(b) for b in scheme.get("benefits") or [])),
        "STATES": _states(scheme.get("applicable_states")),
        "DOCUMENTS": sorted({(text(d.get("name")), bool(d.get("mandatory", True)))
                             for d in scheme.get("required_documents") or []}),
        "STEPS": [text(s.get("description")) for s in sorted(scheme.get("application_steps") or [],
                                                              key=lambda s: s.get("step_number") or 0)
                  if text(s.get("description"))],
        "URLS": [url(scheme.get("official_url")), url(scheme.get("application_url"))],
        "STATUS": text(_v(scheme.get("status")) or "UNKNOWN").upper(),
    }


# ─── diff ─────────────────────────────────────────────────────────────────────

@dataclass
class Change:
    scheme_id: str
    scheme_name: str
    category: str
    summary: str
    before: Any
    after: Any
    provenance: Dict[str, Any]
    consequential: bool = field(init=False)
    fingerprint: str = field(init=False)

    def __post_init__(self):
        self.consequential = self.category in CONSEQUENTIAL
        blob = json.dumps([self.scheme_id, self.category, self.before, self.after], sort_keys=True, default=str)
        self.fingerprint = hashlib.sha256(blob.encode()).hexdigest()


def _display(scheme: dict, category: str) -> Any:
    """What a reviewer sees: the original values of the category's fields (not the canonical form)."""
    return {f: scheme.get(f) for f in CATEGORY_FIELDS[category]}


def _summary(category: str, before: dict, after: dict) -> str:
    if category == "STATUS":
        return f"Status: {_v(before['status'])} → {_v(after['status'])}"
    if category == "STATES":
        b, a = before["applicable_states"] or ["all states"], after["applicable_states"] or ["all states"]
        return f"States: {', '.join(b)} → {', '.join(a)}"
    if category in ("ELIGIBILITY", "BENEFITS", "DOCUMENTS", "STEPS"):
        key = CATEGORY_FIELDS[category][0]
        return f"{LABEL[category]} ({len(before[key] or [])} → {len(after[key] or [])} entries)"
    return LABEL[category]


def provenance(candidate: dict, source_name: str, source_sha256: str) -> Dict[str, Any]:
    return {
        "source_file": source_name, "source_sha256": source_sha256,
        "records": [{k: r.get(k) for k in ("source_id", "url", "source_type", "retrieved_at", "last_verified_at",
                                           "content_hash")} for r in (candidate.get("source_records") or [])][:10],
    }


def diff_corpora(verified: List[dict], candidate: List[dict], source_name: str,
                 source_sha256: str) -> Tuple[List[Change], List[str]]:
    """All meaningful changes and batch warnings (candidate records are already validated)."""
    old = {s["scheme_id"]: s for s in verified}
    new = {s["scheme_id"]: s for s in candidate}
    changes: List[Change] = []
    for sid, cand in sorted(new.items()):
        prov = provenance(cand, source_name, source_sha256)
        if sid not in old:
            changes.append(Change(sid, cand.get("name", sid), "NEW_SCHEME", LABEL["NEW_SCHEME"], None,
                                  {"name": cand.get("name"), "status": _v(cand.get("status"))}, prov))
            continue
        a, b = canonical(old[sid]), canonical(cand)
        for category in CATEGORY_FIELDS:
            if a[category] != b[category]:
                before, after = _display(old[sid], category), _display(cand, category)
                changes.append(Change(sid, cand.get("name", sid), category, _summary(category, before, after),
                                      before, after, prov))
    missing = sorted(set(old) - set(new))
    for sid in missing:
        changes.append(Change(sid, old[sid].get("name", sid), "MISSING_FROM_SOURCE", LABEL["MISSING_FROM_SOURCE"],
                              {"status": _v(old[sid].get("status"))}, None,
                              {"source_file": source_name, "source_sha256": source_sha256, "records": []}))
    warnings = []
    if old and len(missing) / len(old) > SUSPICIOUS_MISSING_SHARE:
        warnings.append(f"{len(missing)} of {len(old)} verified schemes are missing from the source — the scrape "
                        "may be incomplete. Review before approving anything.")
    changed = {c.scheme_id for c in changes if c.category not in ("NEW_SCHEME", "MISSING_FROM_SOURCE")}
    if old and len(changed) / len(old) > SUSPICIOUS_CHANGED_SHARE:
        warnings.append(f"{len(changed)} of {len(old)} schemes changed at once — check the scraper and source "
                        "pages for a layout change before approving.")
    return changes, warnings


def apply_approved(verified: List[dict], candidate: List[dict], approved: List[dict], today: str) -> List[dict]:
    """
    The new verified corpus: the old one with ONLY the approved categories taken from the
    candidate. Approved new schemes are added; an approved MISSING_FROM_SOURCE marks the
    scheme INACTIVE (it is never deleted). Source records gain the candidate's provenance.
    """
    out = {s["scheme_id"]: json.loads(json.dumps(s)) for s in verified}
    cand = {s["scheme_id"]: s for s in candidate}
    touched = set()
    for ch in approved:
        sid, cat = ch["scheme_id"], ch["category"]
        if cat == "NEW_SCHEME":
            out[sid] = json.loads(json.dumps(cand[sid]))
        elif cat == "MISSING_FROM_SOURCE":
            out[sid]["status"] = "INACTIVE"
            out[sid]["review_notes"] = "Not found in the source data; marked inactive after review."
        else:
            for f in CATEGORY_FIELDS[cat]:
                out[sid][f] = json.loads(json.dumps(cand[sid].get(f)))
            known = {r.get("source_id") for r in out[sid].get("source_records") or []}
            out[sid].setdefault("source_records", [])
            out[sid]["source_records"] += [r for r in cand[sid].get("source_records") or []
                                           if r.get("source_id") not in known]
        touched.add(sid)
    for sid in touched:
        out[sid]["last_verified_at"] = today
    return [out[k] for k in sorted(out)]
