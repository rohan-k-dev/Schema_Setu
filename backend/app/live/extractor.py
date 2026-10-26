"""
Field extraction from official source pages (HTML, PDF text, or text supplied by Tavily).

Deterministic and conservative: values are copied from the page with the snippet they came
from (field-level provenance); nothing is inferred, paraphrased or filled in by a model. A
field is only reported when the page actually states it. Eligibility text is evidence for
people to read — it is never turned into an eligibility rule here.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

FIELDS = ("name", "description", "eligibility", "exclusions", "benefits", "benefit_amounts", "income_requirement",
          "land_requirement", "documents", "application_process", "application_url", "important_dates",
          "application_status", "ministry")
CORE_FIELDS = ("eligibility", "benefits", "documents", "application_process")

# Section headings → field (checked in order; first match wins)
_SECTIONS = [
    ("exclusions", r"exclusion|not eligible|ineligib|who (is|are) not|shall not be eligible"),
    ("eligibility", r"eligib|who can apply|who is eligible|beneficiar(y|ies) criteria|target group"),
    ("documents", r"documents? (required|needed)|required documents?|checklist of documents|documents to"),
    ("application_process", r"how to apply|application process|procedure|steps to apply|apply online|registration process"),
    ("benefits", r"benefit|financial assistance|assistance|subsidy|incentive|what (do|will) (you|i) get"),
    ("important_dates", r"important dates|last date|deadline|time ?line|schedule"),
]
_HEADING_MAX = 80

_AMOUNT = re.compile(r"(?:₹|(?<![a-z])(?:rs\.?|inr|rupees))\s*([\d,]+(?:\.\d+)?)\s*(lakh crores?|lakhs? crores?|lakhs?|crores?)?"
                     r"(?:\s*(?:/-)?\s*(?:per|a|each|every)\s+(year|annum|month|instal?ment|hectare|acre|farmer|family))?",
                     re.I)
_DATE = re.compile(r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|"
                   r"oct|nov|dec)[a-z]*\.?,?\s+\d{4}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+"
                   r"\d{1,2},?\s+\d{4})\b", re.I)
_DATE_CONTEXT = re.compile(r"last date|deadline|closing date|apply (by|before)|opens? on|open from|till|until|"
                           r"start date|end date|cut-?off", re.I)
_OPEN = re.compile(r"applications? (are|is) (now )?open|apply now|registration (is )?open", re.I)
_CLOSED = re.compile(r"applications? (are|is|have been) closed|registration (is )?closed|last date (is |has )?(over|passed)"
                     r"|portal (is )?closed", re.I)
_MINISTRY = re.compile(r"\b(Ministry of [A-Z][A-Za-z&,' ]{3,80}?|Department of [A-Z][A-Za-z&,' ]{3,80}?)"
                       r"(?=[.,;:()\n]|\s+(?:Government|Govt|GoI|is|has|under|through|from)\b|$)")
# Sentences are split once (a full stop that isn't inside a decimal such as "0.5 hectare", or a line break) and
# each one is tested: linear in the text length. A sentence-matching regex rescanned at every position and
# took 20–40 s on the 500k+ character texts a web search can return.
_SENT_SPLIT = re.compile(r"(?<!\d)\.|\.(?!\d)|\n")
_INCOME = re.compile(r"\b(income|lakh per annum|annual income|income tax)\b", re.I)
_LAND = re.compile(r"\b(hectares?|acres?|landholdings?|land holdings?|cultivable land|landless)\b", re.I)
MAX_TEXT_CHARS = 200_000                          # longer page / search texts are cut before extraction


def _sentences_with(pattern: re.Pattern, text: str, limit: int = 3) -> List[str]:
    out = []
    for sentence in _SENT_SPLIT.split(text):
        if sentence.strip() and pattern.search(sentence):
            out.append(sentence.strip())
            if len(out) == limit:
                break
    return out
_APPLY_LINK = re.compile(r"apply (online|now|here|for)|online application|new (farmer )?registration|"
                         r"^registration|register (here|now|online)|^apply$|application form", re.I)
_NOT_APPLY = re.compile(r"who can apply|how to apply|eligib|guideline|status|faq", re.I)
_WS = re.compile(r"\s+")


@dataclass
class Value:
    value: Any
    evidence: str                       # the text on the page this came from (≤ 300 chars)


@dataclass
class Extraction:
    fields: Dict[str, Value] = field(default_factory=dict)
    quality: str = "EMPTY"              # COMPLETE (all core fields) / PARTIAL / EMPTY
    content_hash: str = ""
    method: str = ""                    # html / pdf / text

    def found(self) -> List[str]:
        return [f for f in FIELDS if f in self.fields]

    def as_dict(self) -> Dict[str, Any]:
        return {k: {"value": v.value, "evidence": v.evidence} for k, v in self.fields.items()}


def _clean(s: str) -> str:
    return _WS.sub(" ", s or "").strip()


def _ev(s: str) -> str:
    s = _clean(s)
    return s if len(s) <= 300 else s[:297] + "..."


def _heading_field(line: str) -> Optional[str]:
    low = line.lower()
    for name, rx in _SECTIONS:
        if re.search(rx, low):
            return name
    return None


def _is_heading(line: str, tagged: bool) -> bool:
    if tagged:
        return True
    return len(line) <= _HEADING_MAX and not line.endswith(".") and _heading_field(line) is not None


def _lines_from_html(html: str) -> tuple[List[tuple[str, bool]], Dict[str, Any]]:
    """Visible text as (line, is_tagged_heading) pairs in document order, plus page metadata."""
    import lxml.html
    # lxml refuses str input that carries an XML encoding declaration (seen on a real government page)
    doc = lxml.html.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", html, count=1))
    meta: Dict[str, Any] = {"links": []}
    for s in doc.xpath('//script[@type="application/ld+json"]'):
        try:
            data = json.loads(s.text_content())
            items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
            for it in items:
                if isinstance(it, dict) and it.get("name"):
                    meta.setdefault("jsonld", it)
        except (ValueError, AttributeError):
            continue
    title = doc.findtext(".//title") or ""
    meta["title"] = _clean(title)
    og = doc.xpath('//meta[@property="og:title"]/@content')
    meta["og_title"] = _clean(og[0]) if og else ""
    desc = doc.xpath('//meta[@name="description"]/@content') or doc.xpath('//meta[@property="og:description"]/@content')
    meta["description"] = _clean(desc[0]) if desc else ""
    for a in doc.xpath("//a[@href]"):
        meta["links"].append((_clean(a.text_content()), a.get("href")))
    for bad in doc.xpath("//script|//style|//noscript|//nav|//footer|//header|//form|//iframe"):
        bad.drop_tree()
    lines: List[tuple[str, bool]] = []
    blocks = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "td", "th", "dt", "dd", "caption", "summary"}
    for el in doc.iter():
        if not isinstance(el.tag, str):
            continue
        tag = el.tag.lower()
        if tag in blocks or (tag in ("div", "span", "strong", "b") and len(el) == 0):
            text = _clean(el.text_content())
            if text and (not lines or lines[-1][0] != text):
                lines.append((text, tag.startswith("h") and len(tag) == 2))
    h1 = doc.xpath("//h1")
    meta["h1"] = _clean(h1[0].text_content()) if h1 else ""
    return lines, meta


def _lines_from_text(text: str) -> List[tuple[str, bool]]:
    return [(l, False) for l in (_clean(x) for x in re.split(r"\n+|(?<=[.;])\s{2,}", text or "")) if l]


_TIMEISH = re.compile(r"^[\d\s:./-]+$")


def _keep(field_name: str, line: str) -> bool:
    """Drop navigation items, video durations and other non-sentences from a section."""
    if _TIMEISH.match(line):
        return False
    if field_name == "documents":                 # document names are short ("Aadhaar card")
        return len(line) >= 4
    return len(line) >= 25 or bool(re.search(r"₹|rs\.?\s*\d|\d+\s*(%|hectare|acre|lakh|crore)", line, re.I))


def _sections(lines: List[tuple[str, bool]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    current: Optional[str] = None
    for line, tagged in lines:
        if _is_heading(line, tagged):
            current = _heading_field(line)
            continue
        if current and _keep(current, line):
            items = out.setdefault(current, [])
            if any(line in other for other in items):           # a fragment of a line we have
                continue
            items[:] = [o for o in items if o not in line]       # a longer line supersedes its fragments
            if len(items) < 25:
                items.append(line)
    return {k: v for k, v in out.items() if v}


def _amounts(text: str) -> List[Dict[str, Any]]:
    seen, out = set(), []
    for m in _AMOUNT.finditer(text):
        try:
            n = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        unit = (m.group(2) or "").lower()
        n *= (10 ** 12 if "lakh" in unit and "crore" in unit else 100_000 if unit.startswith("lakh")
              else 10_000_000 if unit.startswith("crore") else 1)
        if n < 10:                                   # "Rs. 1" style noise
            continue
        key = (n, (m.group(3) or "").lower())
        if key not in seen:
            seen.add(key)
            ctx = text[max(0, m.start() - 80): m.end() + 60]
            out.append({"amount": int(n) if n == int(n) else n, "per": key[1] or None, "evidence": _ev(ctx)})
    return out[:10]


def _dates(text: str) -> List[Dict[str, str]]:
    out, seen = [], set()
    for m in _DATE.finditer(text):
        ctx = text[max(0, m.start() - 90): m.end() + 30]
        if m.group(1) not in seen and _DATE_CONTEXT.search(ctx):
            seen.add(m.group(1))
            out.append({"date": m.group(1), "evidence": _ev(ctx)})
    return out[:8]


def extract(*, html: str = "", text: str = "", base_url: str = "", official_host_check=None) -> Extraction:
    """Extract scheme fields from one page. `official_host_check(url) -> bool` filters application links."""
    method = "html" if html else "text"
    text = (text or "")[:MAX_TEXT_CHARS]
    if html:
        lines, meta = _lines_from_html(html)
        full = "\n".join(l for l, _ in lines)
    else:
        lines, meta = _lines_from_text(text), {"links": []}
        full = text or ""
    ex = Extraction(method=method, content_hash=hashlib.sha256((full or "").encode()).hexdigest())
    if not full.strip():
        return ex
    f = ex.fields

    jl = meta.get("jsonld") or {}
    name = jl.get("name") or meta.get("h1") or meta.get("og_title") or meta.get("title")
    if name:
        f["name"] = Value(_clean(str(name))[:200], _ev(str(name)))
    desc = jl.get("description") or meta.get("description")
    if desc:
        f["description"] = Value(_clean(str(desc))[:600], _ev(str(desc)))

    sec = _sections(lines)
    for key in ("eligibility", "exclusions", "documents", "application_process"):
        if sec.get(key):
            f[key] = Value(sec[key], _ev(" | ".join(sec[key][:3])))
    if sec.get("benefits"):
        f["benefits"] = Value(sec["benefits"], _ev(" | ".join(sec["benefits"][:3])))

    benefit_text = " ".join(sec.get("benefits", [])) or full
    amounts = _amounts(benefit_text)
    if amounts:
        f["benefit_amounts"] = Value([{k: a[k] for k in ("amount", "per")} for a in amounts], amounts[0]["evidence"])

    elig_text = " ".join(sec.get("eligibility", []) + sec.get("exclusions", [])) or full
    inc = _sentences_with(_INCOME, elig_text)
    if inc:
        f["income_requirement"] = Value([_clean(x) for x in inc], _ev(inc[0]))
    land = _sentences_with(_LAND, elig_text)
    if land:
        f["land_requirement"] = Value([_clean(x) for x in land], _ev(land[0]))

    dates = _dates(" ".join(sec.get("important_dates", [])) + " " + full)
    if dates:
        f["important_dates"] = Value([d["date"] for d in dates], dates[0]["evidence"])
    if _CLOSED.search(full):
        m = _CLOSED.search(full)
        f["application_status"] = Value("CLOSED", _ev(full[max(0, m.start() - 60): m.end() + 60]))
    elif _OPEN.search(full):
        m = _OPEN.search(full)
        f["application_status"] = Value("OPEN", _ev(full[max(0, m.start() - 60): m.end() + 60]))

    mins = [_clean(m.group(1)) for m in _MINISTRY.finditer(full)]
    if mins:
        best = max(set(mins), key=mins.count)
        f["ministry"] = Value(best, _ev(best))

    for label, href in meta.get("links", []):
        if href and label and _APPLY_LINK.search(label) and not _NOT_APPLY.search(label):
            target = urljoin(base_url, href)
            if target.startswith(("http://", "https://")) and (official_host_check is None or official_host_check(target)):
                f["application_url"] = Value(target, _ev(label))
                break

    core = sum(1 for k in CORE_FIELDS if k in f)
    ex.quality = "COMPLETE" if core == len(CORE_FIELDS) else "PARTIAL" if (core or len(f) > 2) else "EMPTY"
    return ex
