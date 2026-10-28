"""
Query-time discovery of official scheme pages through Tavily (docs/LIVE_VERIFICATION.md).

One question runs several searches at once, each scoped to a group of official domains —
the national portals (myScheme, National Portal of India), central ministries / scheme
portals, and the farmer's state portals — plus an open search whose results are kept only
when they come from an official host (new official sources are discovered this way).
Results from all searches ("pages") are merged and de-duplicated by canonical URL.

Only the question's topic, the state and the crop go into a search (docs/PRIVACY.md).
Tavily renders pages, so its page text (raw_content) is used for JavaScript-built official
pages that can't be read directly; that text is labelled as retrieved via Tavily.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from app.core.config import settings
from app.core.logging import get_logger
from app.live.sources import Registry, canonical_url, discovery_domains, registry as default_registry

logger = get_logger(__name__)

_PLACEHOLDER = ("api_key_here", "your_", "changeme", "xxx")


def tavily_configured() -> bool:
    key = (settings.TAVILY_API_KEY or "").strip()
    return bool(key) and not any(p in key.lower() for p in _PLACEHOLDER)


@dataclass
class Hit:
    url: str
    canonical: str
    title: str
    snippet: str
    raw_content: str
    category: str
    found_by: List[str] = field(default_factory=list)       # which searches returned it


@dataclass
class SearchRun:
    group: str
    query: str
    domains: List[str]
    status: str                  # OK / ERROR / TIMEOUT / NOT_CONFIGURED
    results: int = 0
    official: int = 0
    detail: str = ""


@dataclass
class Discovery:
    hits: List[Hit] = field(default_factory=list)
    runs: List[SearchRun] = field(default_factory=list)
    duplicates: int = 0
    non_official_dropped: int = 0
    started_at: Optional[datetime] = None

    @property
    def ok(self) -> bool:
        return any(r.status == "OK" for r in self.runs)


# Only these topic words (and stored scheme names) leave the server with a search — never the
# question itself, which can contain personal details (docs/PRIVACY.md).
TOPIC_WORDS = ("insurance", "crop insurance", "loan", "credit", "subsidy", "pension", "irrigation", "drip", "sprinkler",
               "machinery", "tractor", "dairy", "livestock", "animal husbandry", "fisheries", "seed", "fertiliser",
               "fertilizer", "organic", "solar", "pump", "horticulture", "warehouse", "storage", "market", "income support",
               "soil", "bamboo", "beekeeping", "housing", "employment", "training", "women", "youth", "fpo")


def topic_keywords(text: str) -> str:
    low = (text or "").lower()
    found = [w for w in TOPIC_WORDS if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low)]
    return " ".join(dict.fromkeys(found))


def build_query(topic: str, state: Optional[str], crop: Optional[str]) -> str:
    """topic must already be privacy-safe (topic_keywords() or a stored scheme name)."""
    parts = [p for p in ((topic or "").strip()[:120], state, crop) if p]
    return " ".join(parts + ["farmer government scheme eligibility benefits"])


def _client():
    from app.services.search_service import _get_tavily_client
    return _get_tavily_client()


async def discover(topic: str, state: Optional[str], crop: Optional[str], *, timeout: float,
                   client_factory: Callable[[], Any] = _client, reg: Optional[Registry] = None) -> Discovery:
    reg = reg or default_registry
    out = Discovery(started_at=datetime.now(timezone.utc))
    query = build_query(topic, state, crop)
    groups = discovery_domains(state)
    plan = [(name, query, doms) for name, doms in groups.items()] + [("open", query, [])]
    if not tavily_configured():
        out.runs = [SearchRun(g, q, d, "NOT_CONFIGURED", detail="Tavily isn't configured on this server")
                    for g, q, d in plan]
        return out
    try:
        client = client_factory()
    except Exception as exc:
        out.runs = [SearchRun(g, q, d, "ERROR", detail=type(exc).__name__) for g, q, d in plan]
        return out

    async def one(group: str, q: str, domains: List[str]):
        kwargs: Dict[str, Any] = {"query": q, "search_depth": "advanced", "max_results": settings.LIVE_TAVILY_RESULTS,
                                  "include_raw_content": True}
        if domains:
            kwargs["include_domains"] = domains
        try:
            res = await asyncio.wait_for(asyncio.to_thread(client.search, **kwargs), timeout=timeout)
            return group, q, domains, res, None
        except asyncio.TimeoutError:
            return group, q, domains, None, "TIMEOUT"
        except Exception as exc:
            logger.warning(f"Live discovery search '{group}' failed: {type(exc).__name__}")
            return group, q, domains, None, type(exc).__name__

    by_url: Dict[str, Hit] = {}
    for group, q, domains, res, err in await asyncio.gather(*(one(*p) for p in plan)):
        if err:
            out.runs.append(SearchRun(group, q, domains, "TIMEOUT" if err == "TIMEOUT" else "ERROR", detail=err))
            continue
        items = (res or {}).get("results") or []
        run = SearchRun(group, q, domains, "OK", results=len(items))
        for it in items:
            url = (it.get("url") or "").strip()
            info = reg.classify(url)
            if not info.official:
                out.non_official_dropped += 1
                continue
            run.official += 1
            key = canonical_url(url) or url
            if key in by_url:
                out.duplicates += 1
                by_url[key].found_by.append(group)
                if not by_url[key].raw_content and it.get("raw_content"):
                    by_url[key].raw_content = it["raw_content"]
                continue
            by_url[key] = Hit(url=url, canonical=key, title=(it.get("title") or "").strip(),
                              snippet=(it.get("content") or "").strip(), raw_content=(it.get("raw_content") or ""),
                              category=info.category, found_by=[group])
        out.runs.append(run)
    # national portals and ministries first, then state, then other official hosts; stable within a group
    order = {"NATIONAL_PORTAL": 0, "MINISTRY": 1, "STATE": 2, "OFFICIAL_OTHER": 3}
    out.hits = sorted(by_url.values(), key=lambda h: (order.get(h.category, 9), -len(h.found_by)))
    return out
