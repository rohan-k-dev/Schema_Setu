"""
Query-time discovery and verification (docs/LIVE_VERIFICATION.md).

Per scheme question, within LIVE_BUDGET_SECONDS:
  1. discover  — scoped Tavily searches over official domains (runs alongside the DB / graph search);
  2. select    — discovered official pages + the stored official pages of the top stored candidates,
                 de-duplicated by canonical URL, capped at LIVE_MAX_SOURCES;
  3. retrieve  — each page fetched directly (polite fetcher) or, when it can't be read directly but
                 Tavily returned its text during this search, that text (labelled "via Tavily");
  4. extract   — fields with the snippet they came from;
  5. match     — page → stored scheme (canonical URL, scheme portal host, name / alias); unmatched
                 official scheme pages are reported as new discoveries;
  6. verify    — field by field against the stored record; conflicts are kept, never auto-applied;
  7. record    — provenance snapshot per page (last known-good kept), when the database is available.

Every scheme card then carries a freshness label: LIVE_VERIFIED (an official page was read during
this request), SOURCE_REACHABLE (reached, but its details couldn't be read), CACHED (re-used from an
earlier check — with that time), NOT_VERIFIED (tried and failed — with the reason) or STORED
(not checked now — with the stored verification date). Nothing cached is labelled live.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.logging import get_logger
from app.live import discovery as disc
from app.live import fetcher as fx
from app.live.extractor import Extraction, extract
from app.live.sources import NATIONAL_PORTALS, Registry, canonical_url, host_of, registry as default_registry
from app.live.verifier import CONFLICT, CONFIRMED, EVIDENCE_ONLY, LIVE_ONLY, verify
from app.retrieval.models import RetrievalResult, SourceConflict, SourceTrust, SourceType

logger = get_logger(__name__)

LIVE_VERIFIED, SOURCE_REACHABLE, CACHED, NOT_VERIFIED, STORED = (
    "LIVE_VERIFIED", "SOURCE_REACHABLE", "CACHED", "NOT_VERIFIED", "STORED")
_RANK = {LIVE_VERIFIED: 0, SOURCE_REACHABLE: 1, CACHED: 2, NOT_VERIFIED: 3, STORED: 4}
_DETAIL_FIELDS = ("eligibility", "exclusions", "benefits", "benefit_amounts", "income_requirement", "land_requirement",
                  "documents", "application_process", "application_url", "important_dates", "application_status",
                  "ministry")
_LISTING_URL = re.compile(r"/(search|listing)(/|\?|$)|[?&](page_no|pagenumber|kw|q|sort)=", re.I)
# "Verified live" needs a substantive scheme detail — a ministry name alone doesn't verify a scheme
_SUBSTANTIVE_FIELDS = tuple(f for f in _DETAIL_FIELDS if f != "ministry")


def _iso(d) -> Optional[str]:
    return d.isoformat() if hasattr(d, "isoformat") else d          # datetime or date


@dataclass
class Target:
    url: str
    canonical: str
    hint_scheme: Optional[str] = None          # stored scheme whose official page this is
    hit: Optional[disc.Hit] = None             # Tavily result (may carry rendered page text)


@dataclass
class Outcome:
    web_results: List[RetrievalResult] = field(default_factory=list)
    conflicts: List[SourceConflict] = field(default_factory=list)
    freshness: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    report: Dict[str, Any] = field(default_factory=dict)
    stored_dates: Dict[str, Dict[str, Any]] = field(default_factory=dict)   # catalog rows by scheme id


# ─── catalog of stored schemes (for matching pages to schemes) ────────────────

async def load_catalog() -> List[Dict[str, Any]]:
    from app.database.connection import is_db_available
    from app.database.repositories.base import execute_query
    if not is_db_available():
        return []
    rows = await execute_query(
        "SELECT s.scheme_id, s.name, s.short_name, s.official_url, s.application_url, s.status, s.last_verified_at, "
        "COALESCE(array_agg(DISTINCT a.alias) FILTER (WHERE a.alias IS NOT NULL), '{}') AS aliases, "
        "COALESCE(array_agg(DISTINCT src.url) FILTER (WHERE src.url IS NOT NULL), '{}') AS urls "
        "FROM schemes s LEFT JOIN scheme_aliases a ON a.scheme_id = s.id "
        "LEFT JOIN scheme_sources src ON src.scheme_id = s.id GROUP BY s.id")
    return [dict(r) for r in rows]


def _names(entry: Dict[str, Any]) -> List[str]:
    names = [entry.get("name"), entry.get("short_name"), *(entry.get("aliases") or [])]
    return sorted({n.strip() for n in names if n and len(n.strip()) >= 3}, key=len, reverse=True)


def match_scheme(url: str, ex: Optional[Extraction], title: str, catalog: List[Dict[str, Any]],
                 reg: Registry) -> Optional[str]:
    can = canonical_url(url) or url
    host = host_of(url)
    by_url, host_count = {}, {}
    for e in catalog:
        for u in [e.get("official_url"), e.get("application_url"), *(e.get("urls") or [])]:
            if u:
                by_url.setdefault(canonical_url(u), e["scheme_id"])
                host_count.setdefault(host_of(u), set()).add(e["scheme_id"])
    if can in by_url:
        return by_url[can]
    generic = set(NATIONAL_PORTALS) | {h for h, ids in host_count.items() if len(ids) > 1}
    if host not in generic and len(host_count.get(host, ())) == 1:
        return next(iter(host_count[host]))               # a single scheme's own portal
    heading = " ".join([title or "", (ex.fields["name"].value if ex and "name" in ex.fields else "")]).lower()
    best: Tuple[int, Optional[str]] = (0, None)
    for e in catalog:
        for n in _names(e):
            if re.search(rf"(?<![a-z0-9]){re.escape(n.lower())}(?![a-z0-9])", heading) and len(n) > best[0]:
                best = (len(n), e["scheme_id"])
    return best[1]


def prioritise(db_results: List[RetrievalResult], question: str,
               catalog_by_id: Dict[str, Dict[str, Any]]) -> List[RetrievalResult]:
    """
    Schemes the question names first, then those serving the need it states (e.g. "crop insurance" → PMFBY),
    then those targeted at the farmer's state / crop; otherwise stable (retrieval order).
    """
    from app.recommendation.alternatives import scheme_categories, stated_needs
    q = (question or "").lower()
    needs = set(stated_needs(question or "", {}))

    def score(item):
        i, r = item
        names = _names(catalog_by_id.get(r.scheme_id) or {"name": r.title})
        named = any(re.search(r"(?<![a-z0-9])" + re.escape(n.lower()) + r"(?![a-z0-9])", q) for n in names)
        serves = bool(needs & set(scheme_categories({"name": r.title, "description": r.description,
                                                     "benefit_summary": r.benefits})))
        targeted = len((r.evidence or {}).get("targeting", []))
        return (-(6 * named + 3 * serves + targeted), i)
    return [r for _, r in sorted(enumerate(db_results), key=score)]


def _stored_view(sid: str, db_by_id: Dict[str, RetrievalResult], catalog_by_id: Dict[str, Dict[str, Any]]) -> Dict:
    r, c = db_by_id.get(sid), catalog_by_id.get(sid, {})
    return {"name": (r.title if r else None) or c.get("name"), "benefits": r.benefits if r else None,
            "documents": (r.documents if r else None) or [], "official_url": (r.official_url if r else None)
            or c.get("official_url"), "status": c.get("status") or ("ACTIVE" if r else None),
            "eligibility_summary": r.eligibility_summary if r else None}


# ─── the service ──────────────────────────────────────────────────────────────

class LiveService:
    def __init__(self, fetcher: Optional[fx.Fetcher] = None, reg: Optional[Registry] = None,
                 client_factory=None, catalog_loader=None, snapshot_writer=None):
        self.fetcher = fetcher or fx.fetcher
        self.registry = reg or default_registry
        self.client_factory = client_factory or disc._client
        self.catalog_loader = catalog_loader or load_catalog
        self.snapshot_writer = snapshot_writer

    async def discover(self, topic: str, state: Optional[str], crop: Optional[str]) -> disc.Discovery:
        return await disc.discover(topic, state, crop, timeout=max(1.0, settings.LIVE_BUDGET_SECONDS * 0.6),
                                   client_factory=self.client_factory, reg=self.registry)

    async def verify(self, discovery: disc.Discovery, db_results: List[RetrievalResult], *,
                     started: float, deadline: float, started_at: Optional[datetime] = None,
                     question: str = "") -> Outcome:
        try:
            catalog = await self.catalog_loader()
        except Exception as exc:
            logger.warning(f"Live check: stored catalog unavailable ({type(exc).__name__})")
            catalog = []
        self.registry.add_official_hosts(host_of(u) for e in catalog for u in (e.get("urls") or []))
        catalog_by_id = {e["scheme_id"]: e for e in catalog}
        db_by_id = {r.scheme_id: r for r in db_results if r.scheme_id}
        db_results = prioritise(db_results, question, catalog_by_id)

        # The farmer's top stored schemes get their official pages checked first; discovered pages fill the rest
        # (real searches return many reports / portal listings that would otherwise use up every slot).
        targets: Dict[str, Target] = {}
        for r in db_results[: settings.LIVE_DIRECT_FETCH_SCHEMES]:
            u = r.official_url or r.source_url
            if u and self.registry.classify(u).official:
                key = canonical_url(u) or u
                t = targets.setdefault(key, Target(u, key))
                t.hint_scheme = t.hint_scheme or r.scheme_id
        for hit in discovery.hits:
            if _LISTING_URL.search(hit.url):
                continue                                   # search results / listing pages aren't scheme pages
            t = targets.setdefault(hit.canonical, Target(hit.url, hit.canonical, hit=hit))
            t.hit = t.hit or hit
        chosen = list(targets.values())[: settings.LIVE_MAX_SOURCES]
        skipped = list(targets.values())[settings.LIVE_MAX_SOURCES:]

        async def run(t: Target):
            remaining = deadline - time.monotonic()
            fr = await self.fetcher.fetch(t.url, budget_s=remaining)
            return t, fr

        tasks = [asyncio.create_task(run(t)) for t in chosen]
        done, pending = await asyncio.wait(tasks, timeout=max(0.1, deadline - time.monotonic())) if tasks else (set(), set())
        for p in pending:
            p.cancel()
        results: List[Tuple[Target, fx.FetchResult]] = []
        for t, task in zip(chosen, tasks):
            if task in done and not task.cancelled() and task.exception() is None:
                results.append(task.result())
            else:
                results.append((t, fx.FetchResult(url=t.url, status=fx.TIMEOUT, canonical=t.canonical,
                                                  host=host_of(t.url), category=self.registry.classify(t.url).category,
                                                  checked_at=datetime.now(timezone.utc),
                                                  detail="not checked within this question's time budget")))
        out = await self._assemble(discovery, results, skipped, db_by_id, catalog, catalog_by_id, started,
                                   started_at or datetime.now(timezone.utc))
        out.stored_dates = catalog_by_id
        return out

    async def _assemble(self, discovery, results, skipped, db_by_id, catalog, catalog_by_id, started,
                        started_at) -> Outcome:
        out = Outcome()
        now = datetime.now(timezone.utc)
        sources: List[Dict[str, Any]] = []
        per_scheme: Dict[str, List[Dict[str, Any]]] = {}
        new_found: List[Dict[str, Any]] = []
        for t, fr in results:
            info = self.registry.classify(fr.final_url or t.url)
            ex, method, retrieved_at, verified_now = None, "direct", fr.fetched_at, fr.verified_now
            if fr.ok and fr.status != fx.JS_REQUIRED:
                ex = await self._extract(html=fr.html, text=fr.text if not fr.html else "",
                                         base_url=fr.final_url or t.url)
            elif t.hit and len(t.hit.raw_content or "") > 200:
                ex = await self._extract(text=t.hit.raw_content, base_url=t.url)
                method, retrieved_at, verified_now = "tavily", discovery.started_at, True
            sid = t.hint_scheme or match_scheme(t.url, ex, (t.hit.title if t.hit else ""), catalog, self.registry)
            fields_found = [f for f in (ex.found() if ex else []) if f in _DETAIL_FIELDS]
            src = {"url": fr.final_url or t.url, "host": info.host, "category": info.category, "label": info.label,
                   "method": method, "status": fr.status if method == "direct" else "TAVILY_CONTENT",
                   "direct_status": fr.status, "http_status": fr.http_status,
                   "retrieved_at": _iso(retrieved_at), "checked_at": _iso(fr.checked_at or now),
                   "from_cache": fr.from_cache, "scheme_id": sid, "fields_found": fields_found,
                   "found_by": t.hit.found_by if t.hit else ["stored official page"],
                   "reason": fr.reason if not (verified_now and ex) else ""}
            sources.append(src)
            await self._record(t, fr, ex, sid, method)
            if sid:
                verification = verify(_stored_view(sid, db_by_id, catalog_by_id), ex, src["url"]) if ex else {}
                per_scheme.setdefault(sid, []).append({"source": src, "verification": verification,
                                                       "verified_now": verified_now, "extraction": ex})
            elif ex and ex.quality != "EMPTY" and "name" in ex.fields and (
                    {"eligibility", "benefits"} & set(ex.fields)) and len(new_found) < 3:
                new_found.append({"source": src, "extraction": ex})

        for s in skipped:
            sources.append({"url": s.url, "host": host_of(s.url), "status": "NOT_CHECKED", "method": None,
                            "reason": "Limit of pages per question reached.", "found_by": s.hit.found_by if s.hit else []})

        # per-scheme freshness, merger inputs and conflicts
        for sid, items in per_scheme.items():
            out.freshness[sid] = self._freshness(sid, items, catalog_by_id)
            best = min(items, key=lambda i: _RANK[self._status_of(i)])
            src = best["source"]
            out.web_results.append(RetrievalResult(
                source_type=SourceType.LIVE_WEB, source_id=f"live:{src['url']}", scheme_id=sid,
                title=out.freshness[sid].get("live_name") or "", source_url=src["url"],
                source_name=f"{src['label']} ({src['host']})", source_trust=SourceTrust.OFFICIAL,
                retrieved_at=src["retrieved_at"], evidence={"live": out.freshness[sid]}))
            for item in items:
                for fname, v in item["verification"].items():
                    if v["status"] == CONFLICT and item["verified_now"]:
                        out.conflicts.append(SourceConflict(
                            scheme_id=sid, field=fname,
                            values={"stored": v["stored"], f"live ({item['source']['host']})": v["live"]},
                            sources=["stored record", item["source"]["url"]]))
        for n in new_found:
            ex, src = n["extraction"], n["source"]
            sid = "LIVE_" + hashlib.sha256((canonical_url(src["url"]) or src["url"]).encode()).hexdigest()[:10].upper()
            f = ex.fields
            joined = lambda k: " ".join(f[k].value) if k in f and isinstance(f[k].value, list) else None  # noqa: E731
            out.web_results.append(RetrievalResult(
                source_type=SourceType.LIVE_WEB, source_id=f"live:{src['url']}", scheme_id=sid,
                title=f["name"].value, description=f["description"].value if "description" in f else None,
                benefits=joined("benefits"), eligibility_summary=joined("eligibility"),
                documents=f["documents"].value if "documents" in f else None,
                application_steps=f["application_process"].value if "application_process" in f else None,
                official_url=src["url"], source_url=src["url"], source_name=f"{src['label']} ({src['host']})",
                source_trust=SourceTrust.OFFICIAL, retrieved_at=src["retrieved_at"]))
            out.freshness[sid] = {"status": LIVE_VERIFIED, "label": "Found and read live on an official website just "
                                  "now — not in our verified records yet, so eligibility can't be checked "
                                  "automatically.", "new_discovery": True, "checked_at": src["checked_at"],
                                  "sources": [src], "verified_fields": src["fields_found"],
                                  "fields": {k: {"status": LIVE_ONLY, "live": v.value, "evidence": v.evidence,
                                                 "source_url": src["url"]} for k, v in f.items()},
                                  "conflicts": []}

        out.report = self._report(discovery, sources, new_found, started, started_at, now)
        return out

    @staticmethod
    def _status_of(item) -> str:
        src, ver = item["source"], item["verification"]
        detail = [k for k, v in ver.items() if v["status"] in (CONFIRMED, LIVE_ONLY, EVIDENCE_ONLY, CONFLICT)
                  and k in _SUBSTANTIVE_FIELDS]
        if item["verified_now"] and detail:
            return LIVE_VERIFIED
        if item["verified_now"] or src["direct_status"] == fx.JS_REQUIRED:
            return SOURCE_REACHABLE
        if src["direct_status"] == fx.CACHED:
            return CACHED
        return NOT_VERIFIED

    def _freshness(self, sid, items, catalog_by_id) -> Dict[str, Any]:
        ranked = sorted(items, key=lambda i: _RANK[self._status_of(i)])
        status = self._status_of(ranked[0])
        fields: Dict[str, Any] = {}
        for item in ranked:
            for k, v in item["verification"].items():
                fields.setdefault(k, v)
        verified = sorted(k for k, v in fields.items() if v["status"] in (CONFIRMED, LIVE_ONLY, EVIDENCE_ONLY)
                          and k in _DETAIL_FIELDS)
        conflicts = [{"field": k, "stored": v["stored"], "live": v["live"], "source_url": v["source_url"],
                      "evidence": v["evidence"]} for k, v in fields.items() if v["status"] == CONFLICT]
        best = ranked[0]["source"]
        stored_date = _iso(catalog_by_id.get(sid, {}).get("last_verified_at"))
        label = {
            LIVE_VERIFIED: f"Checked live on {best['host']} just now" + (" (via Tavily)" if best["method"] == "tavily" else ""),
            SOURCE_REACHABLE: f"{best['host']} was reached just now, but its details couldn't be read "
                              f"({best['reason'] or 'no scheme details on the page'}); details below are from our "
                              f"stored records" + (f" (last verified {stored_date[:10]})" if stored_date else ""),
            CACHED: f"Last checked on {best['host']} at {best['retrieved_at']} (re-used; not re-checked now)",
            NOT_VERIFIED: f"Couldn't check {best['host']} now ({best['reason']}); details are from our stored "
                          f"records" + (f" (last verified {stored_date[:10]})" if stored_date else ""),
        }[status]
        ex = ranked[0].get("extraction")
        return {"status": status, "label": label, "checked_at": best["checked_at"], "retrieved_at": best["retrieved_at"],
                "stored_last_verified": stored_date, "sources": [i["source"] for i in ranked],
                "verified_fields": verified if status == LIVE_VERIFIED else [],
                "fields": fields if status == LIVE_VERIFIED else {}, "conflicts": conflicts,
                "live_name": ex.fields["name"].value if ex and "name" in ex.fields else None}

    def _report(self, discovery, sources, new_found, started, started_at, now) -> Dict[str, Any]:
        accessed = [s for s in sources if s.get("status") in (fx.OK, fx.NOT_MODIFIED, "TAVILY_CONTENT")]
        cached = [s for s in sources if s.get("status") == fx.CACHED]
        not_checked = [s for s in sources if s.get("status") == "NOT_CHECKED"]
        failed = [s for s in sources if s not in accessed and s not in cached and s not in not_checked]
        runs = discovery.runs
        dstatus = ("NOT_CONFIGURED" if runs and all(r.status == "NOT_CONFIGURED" for r in runs)
                   else "OK" if runs and all(r.status == "OK" for r in runs)
                   else "PARTIAL" if any(r.status == "OK" for r in runs) else "FAILED")
        warnings = []
        if dstatus == "NOT_CONFIGURED":
            warnings.append("Live web search isn't configured on this server, so new sources weren't searched for; "
                            "only the stored official pages of the top schemes were re-checked.")
        elif dstatus in ("FAILED", "PARTIAL"):
            warnings.append("Live web search " + ("failed" if dstatus == "FAILED" else "partly failed") +
                            "; results may miss recent changes.")
        if not accessed:
            warnings.append("No official source could be read during this request: everything shown comes from our "
                            "stored records — check the official website before applying.")
        elif failed:
            warnings.append(f"{len(failed)} official source(s) couldn't be read now; those schemes show stored "
                            f"information.")
        if not_checked:
            warnings.append(f"{len(not_checked)} more official page(s) were found but not checked (limit of "
                            f"{settings.LIVE_MAX_SOURCES} pages per question).")
        hosts = sorted({s["host"] for s in accessed})
        return {
            "performed": True, "started_at": _iso(started_at),
            "finished_at": _iso(now), "duration_ms": int((time.monotonic() - started) * 1000),
            "discovery": {"status": dstatus, "searches": [r.__dict__ for r in runs],
                          "official_results": len(discovery.hits), "duplicates_merged": discovery.duplicates,
                          "non_official_results_ignored": discovery.non_official_dropped},
            "sources": sources, "sources_accessed": len(accessed), "sources_cached": len(cached),
            "sources_failed": len(failed), "sources_not_checked": len(not_checked), "hosts_accessed": hosts,
            "new_discoveries": [{"name": n["extraction"].fields["name"].value, "url": n["source"]["url"]}
                                for n in new_found],
            "coverage_note": (f"Checked {len(accessed)} official page(s) live" + (f" on {', '.join(hosts)}" if hosts else "")
                              + ". Other government websites were not checked for this question."),
            "warnings": warnings,
        }

    async def _extract(self, **kw) -> Optional[Extraction]:
        """Extraction off the event loop; a page that can't be parsed fails alone, never the whole check."""
        try:
            return await asyncio.to_thread(extract, official_host_check=lambda u: self.registry.classify(u).official,
                                           **kw)
        except Exception as exc:
            logger.warning(f"Live check: page not parseable ({type(exc).__name__}: {str(exc)[:120]})")
            return None

    async def _record(self, t: Target, fr: fx.FetchResult, ex: Optional[Extraction], sid: Optional[str],
                      method: str) -> None:
        writer = self.snapshot_writer
        if writer is None:
            from app.database.connection import is_db_available
            if not is_db_available():
                return
            from app.database.repositories import live_snapshot_repository as repo
            writer = repo.record
        if fr.status == fx.CACHED and method == "direct":
            return                                            # nothing new was retrieved
        ok = fr.verified_now or method == "tavily"
        try:
            await writer(canonical=t.canonical, url=fr.final_url or t.url, host=host_of(t.url),
                         category=self.registry.classify(t.url).category, scheme_id=sid, method=method,
                         status=fr.status if method == "direct" else "TAVILY_CONTENT", http_status=fr.http_status,
                         ok=ok and ex is not None, not_found=fr.status == fx.NOT_FOUND,
                         quality=ex.quality if ex else "EMPTY", fields=ex.as_dict() if ex else {},
                         content_hash=ex.content_hash if ex else "", etag=fr.etag, last_modified=fr.last_modified,
                         error=fr.reason or None)
        except Exception as exc:
            logger.warning(f"Live snapshot not recorded: {type(exc).__name__}")


def stored_freshness(scheme_id: str, catalog_by_id: Dict[str, Dict[str, Any]], reason: str) -> Dict[str, Any]:
    d = _iso(catalog_by_id.get(scheme_id, {}).get("last_verified_at"))
    return {"status": STORED, "label": "From our stored records" + (f" (last verified {d[:10]})" if d else "") +
            f" — {reason}", "stored_last_verified": d, "sources": [], "verified_fields": [], "fields": {},
            "conflicts": []}


live_service = LiveService()
