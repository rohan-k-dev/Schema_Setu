"""
Polite fetching of official source pages (docs/LIVE_VERIFICATION.md).

Rules — enforced here, never bypassed:
  - robots.txt is honoured for our user agent (cached per host); a disallowed page is not fetched;
  - at most one request per host at a time, at least LIVE_HOST_MIN_INTERVAL seconds apart
    (longer when robots.txt asks for a Crawl-delay; pages whose delay doesn't fit the budget are skipped);
  - TLS certificates are always verified; redirects are followed only to official hosts;
  - 401 / 403 / 429, CAPTCHA pages, sign-in walls and JavaScript-only pages are recorded as
    inaccessible — never retried with a different identity, solved, or worked around;
  - responses are size- and time-limited; only HTML and PDF are read.

Cache: successful pages are kept for the source's refresh policy (sources.Registry.ttl) and
re-validated with If-None-Match / If-Modified-Since when stale; failures are cached briefly so a
broken site isn't hit on every question. A result served from cache says so (status CACHED) and
carries the time it was actually retrieved — it is never presented as fetched now.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import re
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.live.sources import FAILURE_TTL_SECONDS, Registry, canonical_url, host_of, registry as default_registry

logger = get_logger(__name__)

# Statuses. "Verified now" = OK or NOT_MODIFIED (the server answered during this request).
OK, NOT_MODIFIED, CACHED = "OK", "NOT_MODIFIED", "CACHED"
ROBOTS_DISALLOWED, ACCESS_DENIED, CAPTCHA, AUTH_REQUIRED, JS_REQUIRED = (
    "ROBOTS_DISALLOWED", "ACCESS_DENIED", "CAPTCHA", "AUTH_REQUIRED", "JS_REQUIRED")
HTTP_ERROR, NOT_FOUND, TIMEOUT, TLS_ERROR, NETWORK_ERROR = "HTTP_ERROR", "NOT_FOUND", "TIMEOUT", "TLS_ERROR", "NETWORK_ERROR"
TOO_LARGE, UNSUPPORTED_TYPE, OFF_DOMAIN_REDIRECT, NOT_OFFICIAL, SKIPPED_CRAWL_DELAY, EMPTY = (
    "TOO_LARGE", "UNSUPPORTED_TYPE", "OFF_DOMAIN_REDIRECT", "NOT_OFFICIAL", "SKIPPED_CRAWL_DELAY", "EMPTY")
SUCCESS = {OK, NOT_MODIFIED}

REASON = {
    ROBOTS_DISALLOWED: "The site's robots.txt doesn't allow automated access to this page.",
    ACCESS_DENIED: "The site refused automated access (HTTP 401/403/429).",
    CAPTCHA: "The site asks for a CAPTCHA; we don't bypass it.",
    AUTH_REQUIRED: "The page needs a sign-in.",
    JS_REQUIRED: "The page builds its content with JavaScript, so its text isn't in the page we can read.",
    NOT_FOUND: "The page no longer exists (HTTP 404/410).",
    HTTP_ERROR: "The site returned an error.",
    TIMEOUT: "The site didn't answer in time.",
    TLS_ERROR: "The site's security certificate couldn't be verified, so we didn't read it.",
    NETWORK_ERROR: "The site couldn't be reached.",
    TOO_LARGE: "The document is too large to read during a question.",
    UNSUPPORTED_TYPE: "The page isn't HTML or PDF.",
    OFF_DOMAIN_REDIRECT: "The page redirects to a site that isn't an official government source.",
    NOT_OFFICIAL: "Not an official government source.",
    SKIPPED_CRAWL_DELAY: "The site asks for a long pause between requests; skipped for this question.",
    EMPTY: "The page had no readable text.",
}

_CAPTCHA = re.compile(r"g-recaptcha|hcaptcha|cf-chl|captcha|verify you are (a )?human|are you a robot", re.I)
_LOGIN = re.compile(r"<input[^>]+type=[\"']?password", re.I)
_JS_ONLY = re.compile(r"needs javascript|enable javascript|requires javascript|you need to enable javascript", re.I)
_TAGS = re.compile(r"<script.*?</script>|<style.*?</style>|<[^>]+>", re.S | re.I)


@dataclass
class FetchResult:
    url: str
    status: str
    canonical: str = ""
    host: str = ""
    category: str = ""
    final_url: Optional[str] = None
    http_status: Optional[int] = None
    content_type: str = ""
    html: str = ""
    text: str = ""
    fetched_at: Optional[datetime] = None       # when the content was actually retrieved from the site
    checked_at: Optional[datetime] = None       # when this request looked at it (network or cache)
    from_cache: bool = False
    elapsed_ms: int = 0
    content_hash: str = ""
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in SUCCESS or (self.status == CACHED and bool(self.text))

    @property
    def verified_now(self) -> bool:
        return self.status in SUCCESS

    @property
    def reason(self) -> str:
        return REASON.get(self.status, "")


@dataclass
class _Robots:
    parser: Optional[robotparser.RobotFileParser]
    allow_all: bool
    crawl_delay: float
    fetched: float


@dataclass
class _Entry:
    result: FetchResult
    expires: float


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _visible_text(html: str) -> str:
    return re.sub(r"\s+", " ", _TAGS.sub(" ", html)).strip()


def pdf_text(data: bytes, max_pages: int = 40) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join((p.extract_text() or "") for p in reader.pages[:max_pages]).strip()


class Fetcher:
    def __init__(self, transport: Optional[httpx.AsyncBaseTransport] = None, reg: Optional[Registry] = None,
                 clock=time.monotonic, sleep=asyncio.sleep):
        self.transport = transport
        self.registry = reg or default_registry
        self.clock, self.sleep = clock, sleep
        self._robots: Dict[str, _Robots] = {}
        self._cache: Dict[str, _Entry] = {}
        self._host_locks: Dict[str, asyncio.Lock] = {}
        self._last_hit: Dict[str, float] = {}
        self.requests = 0                       # network requests made (for tests and reports)

    # ─── plumbing ────────────────────────────────────────────────────────
    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport, verify=True, follow_redirects=False,
                                 timeout=settings.LIVE_FETCH_TIMEOUT,
                                 headers={"User-Agent": settings.LIVE_USER_AGENT,
                                          "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9"})

    async def _polite(self, host: str, delay: float):
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        await lock.acquire()
        wait = self._last_hit.get(host, -1e9) + delay - self.clock()
        if wait > 0:
            await self.sleep(wait)
        return lock

    def _done(self, host: str, lock: asyncio.Lock) -> None:
        self._last_hit[host] = self.clock()
        lock.release()

    async def _robots_for(self, client: httpx.AsyncClient, url: str) -> _Robots:
        parts = urlsplit(url)
        key = f"{parts.scheme}://{parts.netloc}"
        cached = self._robots.get(key)
        if cached and self.clock() - cached.fetched < 24 * 3600:
            return cached
        rob = _Robots(None, True, 0.0, self.clock())
        try:
            self.requests += 1
            r = await client.get(key + "/robots.txt")
            if r.status_code >= 500:                         # unreachable robots.txt: assume disallowed
                rob = _Robots(None, False, 0.0, self.clock())
            elif r.status_code < 400:                        # 4xx: no restrictions (RFC 9309)
                p = robotparser.RobotFileParser()
                p.parse(r.text.splitlines())
                delay = p.crawl_delay(settings.LIVE_USER_AGENT) or 0
                rob = _Robots(p, False, float(delay), self.clock())
        except (httpx.TimeoutException, httpx.TransportError):
            rob = _Robots(None, True, 0.0, self.clock())    # the page fetch itself will report the failure
        self._robots[key] = rob
        return rob

    def _allowed(self, rob: _Robots, url: str) -> bool:
        if rob.parser is None:
            return rob.allow_all
        return rob.parser.can_fetch(settings.LIVE_USER_AGENT, url)

    def _base(self, url: str) -> FetchResult:
        info = self.registry.classify(url)
        return FetchResult(url=url, status="", canonical=canonical_url(url) or url, host=info.host,
                           category=info.category, checked_at=_now())

    def _store(self, res: FetchResult) -> FetchResult:
        ttl = self.registry.ttl(res.final_url or res.url, res.content_type) if res.ok else FAILURE_TTL_SECONDS
        self._cache[res.canonical] = _Entry(res, self.clock() + ttl)
        return res

    # ─── public ──────────────────────────────────────────────────────────
    def cached(self, url: str) -> Optional[FetchResult]:
        e = self._cache.get(canonical_url(url) or url)
        return e.result if e else None

    async def fetch(self, url: str, *, budget_s: Optional[float] = None) -> FetchResult:
        base = self._base(url)
        if not self.registry.classify(url).official:
            return replace(base, status=NOT_OFFICIAL)
        entry = self._cache.get(base.canonical)
        if entry and entry.expires > self.clock():
            hit = entry.result
            status = CACHED if hit.ok else hit.status
            return replace(hit, status=status, from_cache=True, checked_at=_now())
        validators = entry.result if entry and entry.result.ok else None

        async with self._client() as client:
            rob = await self._robots_for(client, url)
            if not self._allowed(rob, url):
                return self._store(replace(base, status=ROBOTS_DISALLOWED))
            delay = max(settings.LIVE_HOST_MIN_INTERVAL, rob.crawl_delay)
            if budget_s is not None and delay > budget_s:
                return replace(base, status=SKIPPED_CRAWL_DELAY)
            lock = await self._polite(base.host, delay)
            try:
                return await self._get(client, base, validators)
            finally:
                self._done(base.host, lock)

    async def _get(self, client: httpx.AsyncClient, base: FetchResult, validators: Optional[FetchResult]) -> FetchResult:
        t0 = time.monotonic()
        headers = {}
        if validators and validators.etag:
            headers["If-None-Match"] = validators.etag
        if validators and validators.last_modified:
            headers["If-Modified-Since"] = validators.last_modified
        url = base.url
        try:
            for _ in range(4):                                     # at most 3 redirects
                self.requests += 1
                async with client.stream("GET", url, headers=headers) as r:
                    if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                        nxt = urljoin(url, r.headers["location"])
                        if not self.registry.classify(nxt).official:
                            return self._store(replace(base, status=OFF_DOMAIN_REDIRECT, http_status=r.status_code,
                                                       final_url=nxt))
                        url = nxt
                        continue
                    res = replace(base, final_url=url, http_status=r.status_code,
                                  content_type=r.headers.get("content-type", ""),
                                  etag=r.headers.get("etag"), last_modified=r.headers.get("last-modified"),
                                  elapsed_ms=int((time.monotonic() - t0) * 1000))
                    if r.status_code == 304 and validators:
                        return self._store(replace(validators, status=NOT_MODIFIED, http_status=304,
                                                   checked_at=_now(), fetched_at=_now(), from_cache=False,
                                                   elapsed_ms=res.elapsed_ms))
                    if r.status_code in (401, 403, 407, 429):
                        return self._store(replace(res, status=ACCESS_DENIED))
                    if r.status_code in (404, 410):
                        return self._store(replace(res, status=NOT_FOUND))
                    if r.status_code >= 400:
                        return self._store(replace(res, status=HTTP_ERROR))
                    data = b""
                    async for chunk in r.aiter_bytes():
                        data += chunk
                        if len(data) > settings.LIVE_MAX_BYTES:
                            return self._store(replace(res, status=TOO_LARGE))
                    return self._store(await asyncio.to_thread(self._read, res, data, r))   # PDF / HTML parsing off the event loop
            return self._store(replace(base, status=HTTP_ERROR, detail="too many redirects"))
        except httpx.TimeoutException:
            return self._store(replace(base, status=TIMEOUT))
        except httpx.ConnectError as exc:
            status = TLS_ERROR if "CERTIFICATE" in str(exc).upper() or "SSL" in str(exc).upper() else NETWORK_ERROR
            return self._store(replace(base, status=status, detail=type(exc).__name__))
        except httpx.HTTPError as exc:
            return self._store(replace(base, status=NETWORK_ERROR, detail=type(exc).__name__))

    def _read(self, res: FetchResult, data: bytes, r: httpx.Response) -> FetchResult:
        ctype = res.content_type.lower()
        now = _now()
        digest = hashlib.sha256(data).hexdigest()
        if "pdf" in ctype or data[:5] == b"%PDF-":
            try:
                text = pdf_text(data)
            except Exception as exc:
                return replace(res, status=EMPTY, detail=f"PDF not readable ({type(exc).__name__})")
            return replace(res, status=OK if text else EMPTY, text=text, fetched_at=now, content_hash=digest,
                           content_type=res.content_type or "application/pdf")
        if "html" not in ctype and "xml" not in ctype and ctype:
            return replace(res, status=UNSUPPORTED_TYPE)
        html = data.decode(r.encoding or "utf-8", errors="replace")
        text = _visible_text(html)
        if _CAPTCHA.search(html) and len(text) < 3000:
            return replace(res, status=CAPTCHA)
        if _LOGIN.search(html) and re.search(r"log ?in|sign ?in", text, re.I) and len(text) < 2500:
            return replace(res, status=AUTH_REQUIRED)
        if (_JS_ONLY.search(text) or ('id="__NEXT_DATA__"' in html and '"pageProps":{}' in html.replace(" ", ""))
                or len(text.split()) < 60):
            return replace(res, status=JS_REQUIRED, html=html, text=text, fetched_at=now, content_hash=digest)
        return replace(res, status=OK, html=html, text=text, fetched_at=now, content_hash=digest)


fetcher = Fetcher()
