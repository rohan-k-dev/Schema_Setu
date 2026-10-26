"""
Find genuinely missing schemes on OFFICIAL government websites and write a candidate corpus for the
reviewed scheme-update pipeline (docs/SCHEME_UPDATES.md, docs/RECOMMENDATIONS.md). Nothing is
published here: detection, an administrator's approval and the publish job still decide.

    python scripts/discover_missing_schemes.py [--out data/incoming/expansion_<date>.json] [--report r.json]
    (run where the network and backend dependencies are available, e.g. the backend container)

For each seed (a known programme and its official page) the page is fetched with the polite live
fetcher (robots.txt, rate limits, official hosts only, no access-control bypass) and parsed by the
deterministic extractor. A record is created only when the page is readable, its title / heading
names the programme, and it states a description plus eligibility or benefits. Every field comes
from that page with its evidence; anything the page doesn't state stays empty. No eligibility rules
are created (they need a person to encode them from the official criteria), so these schemes are
never "eligible" — they appear as alternatives marked "information incomplete / under review".
Seeds already in the corpus (same id, canonical URL or name / alias) are skipped as duplicates.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "backend", Path("/srv/backend")):
    if p.exists():
        sys.path.insert(0, str(p))

# (scheme_id, words the official page title / heading must contain, official URL, level, state or None)
SEEDS = [
    ("PMMSY", ["matsya sampada"], "https://pmmsy.dof.gov.in/", "central", None),
    ("RASHTRIYA_GOKUL_MISSION", ["gokul"], "https://dahd.gov.in/schemes/programmes/rashtriya_gokul_mission", "central", None),
    ("NPDD", ["dairy development"], "https://dahd.gov.in/schemes/programmes/npdd", "central", None),
    ("AHIDF", ["animal husbandry infrastructure"], "https://dahd.gov.in/schemes/programmes/ahidf", "central", None),
    ("NMNF", ["natural farming"], "https://naturalfarming.dac.gov.in/", "central", None),
    ("NBHM", ["beekeeping", "honey"], "https://nbb.gov.in/", "central", None),
    ("PMFME", ["formalisation", "micro food"], "https://pmfme.mofpi.gov.in/", "central", None),
    ("PM_KISAN_SAMPADA", ["kisan sampada"], "https://www.mofpi.gov.in/Schemes/pradhan-mantri-kisan-sampada-yojana", "central", None),
    ("NMEO_OP", ["edible oil", "oil palm"], "https://nmeo.dac.gov.in/", "central", None),
    ("PDMC", ["per drop", "pdmc", "micro irrigation"], "https://pdmc.da.gov.in/", "central", None),
    ("FIDF", ["fisheries and aquaculture infrastructure"], "https://dof.gov.in/fidf", "central", None),
    ("MISS_KISAN_RIN", ["interest subvention", "kisan rin"], "https://fasalrin.gov.in/", "central", None),
    ("RWBCIS", ["weather based crop insurance"], "https://pmfby.gov.in/rwbcis", "central", None),
    ("STATE_OD_KALIA", ["kalia"], "https://kalia.odisha.gov.in/", "state", "Odisha"),
    ("STATE_JH_MMKAY", ["krishi ashirwad"], "https://mmkay.jharkhand.gov.in/", "state", "Jharkhand"),
    ("STATE_CG_RGKNY", ["kisan nyay"], "https://rgkny.cg.nic.in/", "state", "Chhattisgarh"),
    ("STATE_HR_MFMB", ["meri fasal", "मेरी फसल"], "https://fasal.haryana.gov.in/", "state", "Haryana"),
    ("STATE_TS_RYTHU_BIMA", ["rythu bima"], "https://rythubima.telangana.gov.in/", "state", "Telangana"),
]

_DETAIL_LINK = re.compile(r"about|guideline|objective|eligib|component|benefit|operational|scheme|how to apply|faq",
                          re.I)
MAX_SUBPAGES = 4


def detail_links(html: str, base: str, reg) -> list:
    """Same-site links that look like the programme's detail pages or guideline PDFs (max MAX_SUBPAGES)."""
    from urllib.parse import urljoin, urlparse
    import lxml.html
    try:
        doc = lxml.html.fromstring(html)
    except Exception:
        return []
    host, out = urlparse(base).hostname, []
    for a in doc.iter("a"):
        href, text = a.get("href") or "", " ".join(a.itertext()).strip()
        url = urljoin(base, href).split("#")[0]
        if not url.startswith("http") or urlparse(url).hostname != host or url.rstrip("/") == base.rstrip("/"):
            continue
        if (_DETAIL_LINK.search(text) or _DETAIL_LINK.search(href)) and reg.classify(url).official and url not in out:
            out.append(url)
    pdfs = [u for u in out if u.lower().endswith(".pdf")]
    return (pdfs + [u for u in out if u not in pdfs])[:MAX_SUBPAGES]


_BENEFIT_TYPES = (("insurance", ("insurance", "bima")), ("loan", ("loan", "credit", "interest subvention")),
                  ("subsidy", ("subsidy", "subsidies")), ("training", ("training",)),
                  ("infrastructure", ("infrastructure",)),
                  ("financial_assistance", ("financial assistance", "per year", "per annum", "per acre", "rs.", "₹")))


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"\(.*?\)", " ", (s or "").lower())).strip()


def benefit_type(text: str) -> str:
    low = (text or "").lower()
    for t, words in _BENEFIT_TYPES:
        if any(w in low for w in words):
            return t
    return "other"


_ASSISTANCE = re.compile(r"subsid|assistance|grant|incentive|insurance|loan|credit|rs\.?\s?\d|₹|\d+\s?%|per (acre|hectare|year)|"
                         r"farmers? (will|shall|get|receive)|beneficiar", re.I)
_CLAUSE = re.compile(r"^\s*(\d+(\.\d+)+|[ivx]+\.|[a-z]\.)\s", re.I)     # "5.3.2 The Committee…", "x. Joint Secretary"


def benefit_lines(lines):
    """Lines that describe assistance to beneficiaries — not committee / procedure clauses of a circular."""
    return [b for b in lines or [] if _ASSISTANCE.search(b) and not _CLAUSE.search(b) and "committee" not in b.lower()]


def existing_match(rec, aliases):
    """An existing scheme whose name / alias is named in the candidate (same scheme or one of its components)."""
    text = " " + _norm(f"{rec.get('name') or ''} {rec.get('description') or ''}") + " "
    for alias, sid in aliases.items():
        if len(alias) >= 10 and f" {alias} " in text:
            return sid, alias
    return None


def corpus_index(corpus):
    from app.live.sources import canonical_url
    ids = {s["scheme_id"] for s in corpus}
    urls = {canonical_url(u) for s in corpus for u in [s.get("official_url"), s.get("application_url")] if u}
    names = {_norm(n) for s in corpus for n in [s["name"], s.get("short_name") or ""] + (s.get("aliases") or []) if n}
    aliases = {_norm(n): s["scheme_id"] for s in corpus
               for n in [s["name"], s.get("short_name") or ""] + (s.get("aliases") or []) if n}
    return ids, urls, names, aliases


def build_record(seed, fr, ex, today):
    """A canonical record from what the official page states — nothing else."""
    sid, _, url, level, state = seed
    f = ex.fields
    v = lambda k: f[k].value if k in f else None                      # noqa: E731
    ev = lambda k: f[k].evidence if k in f else None                  # noqa: E731
    benefits = [{"type": benefit_type(b), "amount": None, "currency": "INR", "frequency": None, "condition": None,
                 "description": b, "source_text": b} for b in benefit_lines(v("benefits"))[:5]]
    elig = v("eligibility") or []
    host_type = "OFFICIAL_STATE" if level == "state" else "OFFICIAL_CENTRAL"
    return {
        "scheme_id": sid, "name": v("name"), "short_name": None, "aliases": [],
        "description": v("description"), "detailed_description": None,
        "ministry": v("ministry"), "department": None, "level": level, "scheme_type": None,
        "status": "ACTIVE",
        "target_beneficiaries": [], "applicable_states": [state] if state else None,
        "applicable_districts": None, "applicable_crops": None,
        "benefits": benefits,
        "eligibility_summary": " ".join(elig)[:800] or None,
        "eligibility_rules": [],                                          # never invented
        "exclusions": v("exclusions") or [],
        "required_documents": [{"name": d, "mandatory": True, "description": None, "source_text": d}
                               for d in (v("documents") or [])[:15]],
        "aadhaar_requirement": "unknown",
        "application_steps": [{"step_number": i + 1, "description": s, "mode": None}
                              for i, s in enumerate((v("application_process") or [])[:10])],
        "application_mode": [], "application_url": v("application_url"),
        "official_url": fr.final_url or url,
        "source_records": [{"source_id": fr.host.upper().replace(".", "_"), "url": fr.final_url or url,
                            "source_type": host_type, "retrieved_at": today, "last_verified_at": today,
                            "reference_text": (ev("eligibility") or ev("benefits") or ev("description") or "")[:500],
                            "content_hash": fr.content_hash}],
        "last_verified_at": today, "data_version": "1.0", "possible_duplicate": False, "needs_review": True,
        "review_notes": (f"Added from the official page {fr.final_url or url} read on {today} by "
                         f"scripts/discover_missing_schemes.py. Fields were extracted automatically from that page "
                         f"(evidence in source_records); fields it doesn't state are empty. No structured "
                         f"eligibility rules. Status ACTIVE is inferred from a live official page (not stated as "
                         f"closed); confirm before relying on it."),
    }


async def main(out_path: Path, report_path: Path | None):
    from app.live.extractor import extract
    from app.live.fetcher import Fetcher
    from app.live.sources import Registry, canonical_url
    corpus_file = next(p for p in (ROOT / "data" / "validated" / "schemes.json",
                                   Path("/srv/data/validated/schemes.json")) if p.exists())
    corpus = json.loads(corpus_file.read_text(encoding="utf-8"))
    ids, urls, names, aliases = corpus_index(corpus)
    reg, fetcher = Registry(), Fetcher()
    today = datetime.now(timezone.utc).date().isoformat()
    report, added = [], []
    for seed in SEEDS:
        sid, words, url, level, state = seed
        entry = {"scheme_id": sid, "url": url, "checked_at": datetime.now(timezone.utc).isoformat()}
        if sid in ids or canonical_url(url) in urls:
            report.append({**entry, "result": "DUPLICATE_SKIPPED", "detail": "already in the corpus"})
            continue
        fr = await fetcher.fetch(url)
        entry.update(fetch_status=fr.status, http_status=fr.http_status, final_url=fr.final_url)
        if not fr.ok:
            report.append({**entry, "result": "NOT_ADDED", "detail": fr.reason})
            continue
        check = lambda u: reg.classify(u).official                       # noqa: E731
        ex = extract(html=fr.html or "", text=fr.text if not fr.html else "", base_url=fr.final_url or url,
                     official_host_check=check)
        pages = [fr.final_url or url]
        if not ({"eligibility", "benefits"} & set(ex.found())) and fr.html:
            for sub in detail_links(fr.html, fr.final_url or url, reg):   # follow the programme's own detail pages
                sfr = await fetcher.fetch(sub)
                entry.setdefault("subpages", []).append({"url": sub, "status": sfr.status})
                if not sfr.ok:
                    continue
                sex = extract(html=sfr.html or "", text=sfr.text if not sfr.html else "", base_url=sfr.final_url or sub,
                              official_host_check=check)
                new = {k: v for k, v in sex.fields.items() if k not in ex.fields and k != "name"}
                if new:
                    ex.fields.update(new)                                  # each field keeps its own page's evidence
                    pages.append(sfr.final_url or sub)
        entry["pages_used"] = pages
        title = " ".join(str(ex.fields[k].value) for k in ("name",) if k in ex.fields) + " " + \
            (re.search(r"<title[^>]*>(.*?)</title>", fr.html or "", re.I | re.S) or [None, ""])[1]
        found = sorted(ex.found())
        entry.update(fields_found=found, quality=ex.quality, page_title=title.strip()[:200])
        if not any(w in title.lower() for w in words):
            report.append({**entry, "result": "NOT_ADDED", "detail": "page title / heading doesn't name the programme"})
            continue
        if "description" not in ex.fields or not ({"eligibility", "benefits"} & set(found)):
            report.append({**entry, "result": "NOT_ADDED",
                           "detail": "page doesn't state a description plus eligibility or benefits"})
            continue
        if ex.fields.get("application_status") and ex.fields["application_status"].value == "CLOSED":
            report.append({**entry, "result": "NOT_ADDED", "detail": "page says the scheme is closed"})
            continue
        rec = build_record(seed, fr, ex, today)
        for extra in pages[1:]:
            rec["source_records"].append({**rec["source_records"][0], "url": extra, "content_hash": None,
                                          "reference_text": None})
        same = existing_match(rec, aliases)
        if same:
            report.append({**entry, "result": "DUPLICATE_SKIPPED",
                           "detail": f"names '{same[1]}', already in the corpus as {same[0]} (same scheme or its component)"})
            continue
        if not rec["benefits"] and not rec["eligibility_summary"]:
            report.append({**entry, "result": "NOT_ADDED", "detail": "no beneficiary benefits or eligibility stated"})
            continue
        if _norm(rec["name"]) in names:
            report.append({**entry, "result": "DUPLICATE_SKIPPED", "detail": f"name already in corpus: {rec['name']}"})
            continue
        added.append(rec)
        names.add(_norm(rec["name"]))
        report.append({**entry, "result": "ADDED_AS_CANDIDATE", "name": rec["name"]})
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(corpus + added, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = {"corpus_before": len(corpus), "candidates_added": len(added), "seeds_checked": len(SEEDS),
               "network_requests": fetcher.requests, "results": report}
    if report_path:
        report_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    for r in report:
        print(f"{r['result']:<19} {r['scheme_id']:<26} {r.get('fetch_status', ''):<14} "
              f"{r.get('detail') or r.get('name') or ''}"[:200])
    print(f"\n{len(added)} candidate record(s) added to {out_path} (corpus had {len(corpus)}).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    day = datetime.now(timezone.utc).date().isoformat()
    ap.add_argument("--out", default=str(ROOT / "data" / "incoming" / f"expansion_{day}.json"))
    ap.add_argument("--report", default=None)
    a = ap.parse_args()
    asyncio.run(main(Path(a.out), Path(a.report) if a.report else None))
