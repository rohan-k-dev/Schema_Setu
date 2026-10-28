"""
Query-time discovery and verification of official sources (docs/LIVE_VERIFICATION.md),
with saved HTML / PDF fixtures and mocked network responses (httpx.MockTransport, a fake Tavily
client) so every case is repeatable: live search across several official domains, fetching and
parsing, pagination and duplicates, HTTP errors / timeouts / inaccessible pages, robots.txt and
access controls, missing and conflicting fields, cache freshness and fallback, evidence-backed
results, source URLs and timestamps, provenance (last known-good), and the full retrieval step.

The real network run is scripts/live_check.py (reported separately — these tests prove the logic,
not that any given government site is reachable today).
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest

from app.core.config import settings
from app.live import fetcher as fx
from app.live.discovery import build_query, discover, topic_keywords
from app.live.extractor import extract
from app.live.service import CACHED, LIVE_VERIFIED, NOT_VERIFIED, SOURCE_REACHABLE, STORED, LiveService
from app.live.sources import Registry, canonical_url
from app.live.verifier import CONFIRMED, CONFLICT, LIVE_ONLY, STORED_ONLY, verify
from app.database.repositories.live_snapshot_repository import classify
from app.retrieval.models import RetrievalResult, SourceTrust, SourceType

FIX = Path(__file__).parent / "fixtures" / "live"


def fixture(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def make_pdf(lines: List[str]) -> bytes:
    """A real, minimal PDF with text (Helvetica) — read back by pypdf like a guidelines document."""
    content = "BT /F1 12 Tf 72 720 Td 16 TL " + " ".join(f"({l}) Tj T*" for l in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    return out + f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()


# ─── a fake web: routes, robots.txt, errors; records every request ───────────

class FakeWeb:
    def __init__(self):
        self.routes: Dict[str, Any] = {}       # url -> (status, headers, body) | Exception | callable
        self.robots: Dict[str, str] = {}       # "https://host" -> robots.txt body
        self.log: List[httpx.Request] = []

    def page(self, url, body, status=200, ctype="text/html; charset=utf-8", headers=None):
        self.routes[url] = (status, {"content-type": ctype, **(headers or {})}, body)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.log.append(request)
        url = str(request.url)
        if request.url.path == "/robots.txt":
            body = self.robots.get(f"{request.url.scheme}://{request.url.host}")
            return httpx.Response(404) if body is None else httpx.Response(200, text=body)
        route = self.routes.get(url) or self.routes.get(url.rstrip("/"))
        if route is None:
            return httpx.Response(404, text="not found")
        if callable(route):
            return route(request)
        if isinstance(route, Exception):
            raise route
        status, headers, body = route
        return httpx.Response(status, headers=headers, content=body if isinstance(body, bytes) else body.encode())

    def page_requests(self, url):
        return [r for r in self.log if str(r.url).rstrip("/") == url.rstrip("/")]


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.slept: List[float] = []

    def __call__(self):
        return self.t

    async def sleep(self, s):
        self.slept.append(s)
        self.t += s


@pytest.fixture
def web(monkeypatch):
    monkeypatch.setattr(settings, "LIVE_HOST_MIN_INTERVAL", 1.0)
    return FakeWeb()


def make_fetcher(web, clock=None):
    clock = clock or Clock()
    return fx.Fetcher(transport=httpx.MockTransport(web.handler), clock=clock, sleep=clock.sleep), clock


# ─── official source registry ────────────────────────────────────────────────

class TestRegistry:
    def test_classification_uses_the_hostname(self):
        r = Registry()
        assert r.classify("https://www.myscheme.gov.in/schemes/kcc").category == "NATIONAL_PORTAL"
        assert r.classify("https://pmkisan.gov.in/").category == "MINISTRY"
        assert r.classify("https://raitamitra.karnataka.gov.in/x").category == "STATE"
        assert r.classify("https://someboard.gov.in/").category == "OFFICIAL_OTHER"
        for bad in ("https://evil.example/?x=.gov.in", "https://gov.in.evil.example/", "https://pmkisan.gov.in.evil.com/",
                    "javascript:alert(1)", "ftp://pmkisan.gov.in/"):
            assert not r.classify(bad).official, bad
        assert r.classify("https://maandhan.in/").official                   # explicitly listed official site
        assert not r.classify("https://nsmny-copy.org/").official
        r.add_official_hosts(["nsmny.mahait.org"])                            # learned from stored sources
        assert r.classify("https://nsmny.mahait.org/apply").official

    def test_source_specific_refresh_policy(self):
        r = Registry()
        assert r.ttl("https://www.myscheme.gov.in/x") == 12 * 3600
        assert r.ttl("https://pmkisan.gov.in/") == 24 * 3600
        assert r.ttl("https://agriwelfare.gov.in/guidelines.pdf") == 7 * 24 * 3600
        assert canonical_url("https://www.PMKISAN.gov.in/a/?utm_source=x#top") == canonical_url("http://pmkisan.gov.in/a")


# ─── discovery (live search across official domains) ─────────────────────────

class FakeTavily:
    def __init__(self, by_group=None, fail_groups=(), slow_groups=()):
        self.calls: List[Dict[str, Any]] = []
        self.by_group = by_group or {}
        self.fail, self.slow = set(fail_groups), set(slow_groups)

    def _group(self, kwargs):
        doms = kwargs.get("include_domains") or []
        if not doms:
            return "open"
        if "myscheme.gov.in" in doms:
            return "national"
        if "agriwelfare.gov.in" in doms:
            return "ministry"
        return "state"

    def search(self, **kwargs):
        self.calls.append(kwargs)
        g = self._group(kwargs)
        if g in self.fail:
            raise RuntimeError("upstream error")
        if g in self.slow:
            time.sleep(0.5)
        return {"results": self.by_group.get(g, [])}


def tav(url, title="", content="", raw=""):
    return {"url": url, "title": title, "content": content, "raw_content": raw}


class TestDiscovery:
    @pytest.mark.asyncio
    async def test_searches_several_official_domain_groups_and_merges_pages(self, monkeypatch):
        monkeypatch.setattr(settings, "TAVILY_API_KEY", "tvly-test-key")
        t = FakeTavily({
            "national": [tav("https://www.myscheme.gov.in/schemes/pm-kisan", "PM-KISAN | myScheme"),
                         tav("https://www.india.gov.in/spotlight/pm-kisan", "PM-KISAN | NPI")],
            "ministry": [tav("https://pmkisan.gov.in/", "PM-KISAN"),
                         tav("https://www.myscheme.gov.in/schemes/pm-kisan?utm_source=x", "dup")],
            "state": [tav("https://raitamitra.karnataka.gov.in/scheme", "Raitha Siri")],
            "open": [tav("https://blog.example.com/pm-kisan", "blog"), tav("https://newboard.gov.in/scheme", "New")],
        })
        d = await discover("income support", "Karnataka", "ragi", timeout=5, client_factory=lambda: t)
        groups = {c.get("include_domains", ["<open>"])[0] for c in t.calls}
        assert len(t.calls) == 4 and {"myscheme.gov.in", "agriwelfare.gov.in", "raitamitra.karnataka.gov.in",
                                      "<open>"} == groups
        assert all(c["include_raw_content"] and c["max_results"] == settings.LIVE_TAVILY_RESULTS for c in t.calls)
        urls = [h.url for h in d.hits]
        assert len(urls) == 5 and d.duplicates == 1 and d.non_official_dropped == 1      # pages merged, deduped
        assert "https://newboard.gov.in/scheme" in urls                                  # new official source
        assert [h.category for h in d.hits][:2] == ["NATIONAL_PORTAL", "NATIONAL_PORTAL"]
        dup = next(h for h in d.hits if "myscheme" in h.url)
        assert sorted(dup.found_by) == ["ministry", "national"]

    @pytest.mark.asyncio
    async def test_no_personal_data_leaves_in_the_query(self, monkeypatch):
        monkeypatch.setattr(settings, "TAVILY_API_KEY", "tvly-test-key")
        t = FakeTavily()
        topic = topic_keywords("I am 45 years old, SC category, income 2 lakh, need crop insurance")
        await discover(topic, "Karnataka", "ragi", timeout=5, client_factory=lambda: t)
        q = t.calls[0]["query"]
        assert q == build_query("crop insurance insurance", "Karnataka", "ragi") or "insurance" in q
        for leaked in ("45", "SC", "2 lakh", "income 2"):
            assert leaked not in q

    @pytest.mark.asyncio
    async def test_not_configured_and_partial_failures_are_reported(self, monkeypatch):
        monkeypatch.setattr(settings, "TAVILY_API_KEY", "API_KEY_HERE")             # placeholder = not configured
        d = await discover("", "Karnataka", None, timeout=5, client_factory=lambda: pytest.fail("no client"))
        assert {r.status for r in d.runs} == {"NOT_CONFIGURED"} and not d.ok
        monkeypatch.setattr(settings, "TAVILY_API_KEY", "tvly-test-key")
        t = FakeTavily({"national": [tav("https://www.myscheme.gov.in/schemes/kcc")]}, fail_groups={"ministry"},
                       slow_groups={"state"})
        d = await discover("", "Karnataka", None, timeout=0.2, client_factory=lambda: t)
        statuses = {r.group: r.status for r in d.runs}
        assert statuses == {"national": "OK", "ministry": "ERROR", "state": "TIMEOUT", "open": "OK"} and d.ok


# ─── polite fetching ─────────────────────────────────────────────────────────

class TestFetcher:
    @pytest.mark.asyncio
    async def test_reads_html_and_pdf(self, web):
        web.page("https://raitamitra.karnataka.gov.in/scheme", fixture("state_scheme.html"))
        web.page("https://agriwelfare.gov.in/guidelines.pdf",
                 make_pdf(["Guidelines for Raitha Siri", "Eligibility", "Farmers with up to 2 hectare land.",
                           "Benefits", "Rs. 10,000 per hectare for millet growers."]), ctype="application/pdf")
        f, _ = make_fetcher(web)
        html = await f.fetch("https://raitamitra.karnataka.gov.in/scheme")
        assert html.status == fx.OK and html.http_status == 200 and "Raitha Siri" in html.text
        assert html.fetched_at and html.content_hash and html.verified_now
        pdf = await f.fetch("https://agriwelfare.gov.in/guidelines.pdf")
        assert pdf.status == fx.OK and "10,000 per hectare" in pdf.text

    @pytest.mark.asyncio
    async def test_robots_txt_is_honoured(self, web):
        web.robots["https://pmfby.gov.in"] = "User-agent: *\nDisallow: /private/\n"
        web.page("https://pmfby.gov.in/private/scheme", "<html>secret</html>")
        f, _ = make_fetcher(web)
        r = await f.fetch("https://pmfby.gov.in/private/scheme")
        assert r.status == fx.ROBOTS_DISALLOWED and not web.page_requests("https://pmfby.gov.in/private/scheme")

    @pytest.mark.parametrize("route,status", [
        ((403, {}, "denied"), fx.ACCESS_DENIED), ((429, {}, "slow down"), fx.ACCESS_DENIED),
        ((404, {}, "gone"), fx.NOT_FOUND), ((503, {}, "down"), fx.HTTP_ERROR),
        (httpx.ReadTimeout("slow"), fx.TIMEOUT),
        (httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed"), fx.TLS_ERROR),
        (httpx.ConnectError("getaddrinfo failed"), fx.NETWORK_ERROR),
    ])
    @pytest.mark.asyncio
    async def test_http_errors_timeouts_and_unreachable_pages(self, web, route, status):
        url = "https://pmkisan.gov.in/page"
        if isinstance(route, Exception):
            web.routes[url] = route
        else:
            web.page(url, route[2], status=route[0])
        f, _ = make_fetcher(web)
        r = await f.fetch(url)
        assert r.status == status and not r.ok and r.reason

    @pytest.mark.parametrize("name,status", [("captcha.html", fx.CAPTCHA), ("login.html", fx.AUTH_REQUIRED),
                                             ("myscheme_shell.html", fx.JS_REQUIRED)])
    @pytest.mark.asyncio
    async def test_access_controls_are_recorded_never_bypassed(self, web, name, status):
        url = "https://www.myscheme.gov.in/schemes/pm-kisan"
        web.page(url, fixture(name))
        f, _ = make_fetcher(web)
        r = await f.fetch(url)
        assert r.status == status
        assert len(web.page_requests(url)) == 1                  # one polite request; no retries or tricks

    @pytest.mark.asyncio
    async def test_redirects_only_to_official_hosts(self, web):
        web.page("https://pmkisan.gov.in/old", "", status=301, headers={"location": "https://pmkisan.gov.in/new"})
        web.page("https://pmkisan.gov.in/new", fixture("ministry_pmkisan.html"))
        web.page("https://pmkisan.gov.in/out", "", status=302, headers={"location": "https://ads.example.com/x"})
        f, _ = make_fetcher(web)
        ok = await f.fetch("https://pmkisan.gov.in/old")
        assert ok.status == fx.OK and ok.final_url == "https://pmkisan.gov.in/new"
        bad = await f.fetch("https://pmkisan.gov.in/out")
        assert bad.status == fx.OFF_DOMAIN_REDIRECT and not web.page_requests("https://ads.example.com/x")

    @pytest.mark.asyncio
    async def test_size_type_and_official_limits(self, web, monkeypatch):
        monkeypatch.setattr(settings, "LIVE_MAX_BYTES", 10_000)
        web.page("https://pmkisan.gov.in/big", "x" * 20_000)
        web.page("https://pmkisan.gov.in/img", b"\x89PNG", ctype="image/png")
        f, _ = make_fetcher(web)
        assert (await f.fetch("https://pmkisan.gov.in/big")).status == fx.TOO_LARGE
        assert (await f.fetch("https://pmkisan.gov.in/img")).status == fx.UNSUPPORTED_TYPE
        assert (await f.fetch("https://blog.example.com/pm-kisan")).status == fx.NOT_OFFICIAL
        assert not [r for r in web.log if r.url.host == "blog.example.com"]

    @pytest.mark.asyncio
    async def test_cache_freshness_revalidation_and_failure_cache(self, web):
        url = "https://pmkisan.gov.in/scheme"
        calls = {"n": 0}

        def respond(request):
            calls["n"] += 1
            if request.headers.get("if-none-match") == '"v1"':
                return httpx.Response(304)
            return httpx.Response(200, headers={"content-type": "text/html", "etag": '"v1"'},
                                  content=fixture("ministry_pmkisan.html").encode())
        web.routes[url] = respond
        f, clock = make_fetcher(web)
        first = await f.fetch(url)
        assert first.status == fx.OK and calls["n"] == 1
        again = await f.fetch(url)                                     # within the 24 h policy
        assert again.status == fx.CACHED and again.from_cache and not again.verified_now
        assert again.fetched_at == first.fetched_at and calls["n"] == 1   # cached time kept, never "now"
        clock.t += 25 * 3600                                           # past the policy: re-validate
        reval = await f.fetch(url)
        assert reval.status == fx.NOT_MODIFIED and reval.verified_now and calls["n"] == 2
        assert reval.fetched_at > first.fetched_at and "PM-KISAN" in reval.text
        web.routes["https://pmfby.gov.in/"] = httpx.ConnectError("refused")
        await f.fetch("https://pmfby.gov.in/")
        n = len(web.log)
        again_fail = await f.fetch("https://pmfby.gov.in/")             # failure cached briefly: not hammered
        assert again_fail.status == fx.NETWORK_ERROR and again_fail.from_cache and len(web.log) == n

    @pytest.mark.asyncio
    async def test_per_host_rate_limit_and_crawl_delay(self, web, monkeypatch):
        web.robots["https://raitamitra.karnataka.gov.in"] = "User-agent: *\nCrawl-delay: 3\n"
        web.page("https://raitamitra.karnataka.gov.in/a", fixture("state_scheme.html"))
        web.page("https://raitamitra.karnataka.gov.in/b", fixture("state_scheme.html"))
        web.robots["https://slow.gov.in"] = "User-agent: *\nCrawl-delay: 60\n"
        web.page("https://slow.gov.in/x", fixture("state_scheme.html"))
        f, clock = make_fetcher(web)
        await asyncio.gather(f.fetch("https://raitamitra.karnataka.gov.in/a"),
                             f.fetch("https://raitamitra.karnataka.gov.in/b"))
        assert clock.slept and max(clock.slept) >= 3.0                  # second request waited for the delay
        skipped = await f.fetch("https://slow.gov.in/x", budget_s=8)
        assert skipped.status == fx.SKIPPED_CRAWL_DELAY and not web.page_requests("https://slow.gov.in/x")


# ─── extraction ──────────────────────────────────────────────────────────────

class TestExtraction:
    def test_state_page_fields_with_evidence(self):
        reg = Registry()
        ex = extract(html=fixture("state_scheme.html"), base_url="https://raitamitra.karnataka.gov.in/scheme",
                     official_host_check=lambda u: reg.classify(u).official)
        f = ex.fields
        assert ex.quality == "COMPLETE"
        assert f["name"].value == "Raitha Siri - Karnataka Farmer Income Support"
        assert any("0.5 hectare" in x for x in f["eligibility"].value)
        assert any("income tax" in x for x in f["exclusions"].value)
        assert {"amount": 10000, "per": "hectare"} in f["benefit_amounts"].value
        assert "Rs. 10,000 per hectare" in f["benefit_amounts"].evidence
        assert f["documents"].value[:2] == ["Aadhaar card", "Land records (RTC / Pahani)"]
        assert len(f["application_process"].value) == 3
        assert f["application_url"].value == "https://fruits.karnataka.gov.in/apply"     # official, not 3rd-party
        assert f["important_dates"].value == ["31-12-2026"] and f["application_status"].value == "OPEN"
        assert f["ministry"].value in ("Department of Agriculture", "Ministry of Agriculture and Farmers Welfare")
        assert any("2 hectares" in x for x in f["land_requirement"].value)
        assert "Benefits" not in f["benefits"].value and "Contact" not in str(f["benefits"].value)  # no menu items

    def test_structured_data_and_missing_fields(self):
        ex = extract(html=fixture("ministry_pmkisan.html"), base_url="https://pmkisan.gov.in/")
        f = ex.fields
        assert f["name"].value == "Pradhan Mantri Kisan Samman Nidhi (PM-KISAN)"                 # JSON-LD
        assert f["application_url"].value == "https://pmkisan.gov.in/RegistrationForm.aspx"
        assert "important_dates" not in f and "application_status" not in f                     # not stated: absent

    def test_pdf_text_and_empty_pages(self):
        text = fx.pdf_text(make_pdf(["Eligibility", "Farmers with up to 2 hectare land are eligible for support.",
                                     "Benefits", "Rs. 10,000 per hectare for millet growers in the season."]))
        ex = extract(text=text)
        assert ex.fields["benefit_amounts"].value[0]["amount"] == 10000 and "eligibility" in ex.fields
        assert extract(html="<html><body></body></html>").quality == "EMPTY"
        assert "benefit_amounts" not in extract(text="Office hours 10 to 5. Contact: Rs. desk").fields


# ─── verification against stored records ─────────────────────────────────────

class TestVerifier:
    def test_confirmed_conflicting_and_stored_only_fields(self):
        stored = {"benefits": "Rs. 6,000 per year in three instalments", "documents": ["Aadhaar Card", "Land Records"],
                  "official_url": "https://pmkisan.gov.in", "status": "ACTIVE"}
        v = verify(stored, extract(html=fixture("ministry_pmkisan.html"), base_url="https://pmkisan.gov.in/"),
                   "https://pmkisan.gov.in/")
        assert v["benefit_amounts"]["status"] == CONFIRMED and v["documents"]["status"] == CONFIRMED
        assert v["application_url"]["status"] == CONFIRMED and v["benefit_amounts"]["source_url"]
        stored_pmfby = {"benefits": "Sum insured as per scale of finance; premium 2% for Kharif",
                        "documents": ["Aadhaar Card", "Bank Passbook"], "status": "ACTIVE",
                        "official_url": "https://pmfby.gov.in"}
        v2 = verify(stored_pmfby, extract(html=fixture("conflicting_pmfby.html")), "https://pmfby.gov.in/")
        assert v2["application_status"]["status"] == CONFLICT                       # page says closed
        assert v2["documents"]["status"] == CONFLICT                                 # no common documents
        assert v2["benefit_amounts"]["status"] == LIVE_ONLY                          # nothing stored to compare
        v3 = verify(stored, extract(text="Contact us. Office hours 10 to 5."), "https://pmkisan.gov.in/contact")
        assert v3["benefit_amounts"]["status"] == STORED_ONLY and v3["documents"]["status"] == STORED_ONLY


# ─── provenance: never overwrite a valid record with a worse one ─────────────

class TestProvenanceRule:
    def test_change_classification(self):
        good = {"last_good": {"eligibility": 1, "benefits": 1, "documents": 1}, "last_good_hash": "h1",
                "last_good_quality": "COMPLETE"}
        full = {"eligibility": 1, "benefits": 1, "documents": 1}
        assert classify(None, True, False, "COMPLETE", full, "h1") == ("NEW", True)
        assert classify(good, True, False, "COMPLETE", full, "h1") == ("UNCHANGED", True)
        assert classify(good, True, False, "COMPLETE", {**full, "ministry": 1}, "h2") == ("UPDATED", True)
        assert classify(good, True, False, "PARTIAL", {"eligibility": 1}, "h3") == ("INCOMPLETE", False)
        assert classify(good, True, False, "EMPTY", {}, "h4") == ("UNPARSEABLE", False)
        assert classify(good, False, True, "EMPTY", {}, "") == ("MISSING", False)
        assert classify(good, False, False, "EMPTY", {}, "") == ("FAILED", False)


# ─── the service: discovery + fetch + verify + freshness ─────────────────────

CATALOG = [
    {"scheme_id": "PM_KISAN", "name": "Pradhan Mantri Kisan Samman Nidhi", "short_name": "PM-KISAN",
     "aliases": ["PM Kisan"], "official_url": "https://pmkisan.gov.in", "application_url": None,
     "urls": ["https://pmkisan.gov.in"], "status": "ACTIVE", "last_verified_at": datetime(2026, 9, 26).date()},
    {"scheme_id": "PMFBY", "name": "Pradhan Mantri Fasal Bima Yojana", "short_name": "PMFBY", "aliases": [],
     "official_url": "https://pmfby.gov.in", "application_url": None, "urls": ["https://pmfby.gov.in"],
     "status": "ACTIVE", "last_verified_at": datetime(2026, 9, 26).date()},
    {"scheme_id": "KCC", "name": "Kisan Credit Card", "short_name": "KCC", "aliases": [],
     "official_url": "https://www.myscheme.gov.in/schemes/kcc", "application_url": None,
     "urls": ["https://www.myscheme.gov.in/schemes/kcc"], "status": "ACTIVE",
     "last_verified_at": datetime(2026, 9, 26).date()},
    {"scheme_id": "MGNREGA", "name": "Mahatma Gandhi National Rural Employment Guarantee Act", "short_name": "MGNREGA",
     "aliases": [], "official_url": "https://nrega.nic.in", "application_url": None, "urls": ["https://nrega.nic.in"],
     "status": "ACTIVE", "last_verified_at": datetime(2026, 9, 26).date()},
]


def stored(sid, benefits=None, docs=None, url=None):
    return RetrievalResult(source_type=SourceType.DATABASE, scheme_id=sid, title=sid, benefits=benefits,
                           documents=docs, official_url=url, source_trust=SourceTrust.OFFICIAL,
                           retrieved_at=datetime.now(timezone.utc).isoformat())


@pytest.fixture
def live(web, monkeypatch):
    monkeypatch.setattr(settings, "TAVILY_API_KEY", "tvly-test-key")
    monkeypatch.setattr(settings, "LIVE_BUDGET_SECONDS", 9.0)
    web.page("https://pmkisan.gov.in", fixture("ministry_pmkisan.html"))
    web.page("https://pmfby.gov.in", fixture("conflicting_pmfby.html"))
    web.page("https://www.myscheme.gov.in/schemes/kcc", fixture("myscheme_shell.html"))
    web.routes["https://nrega.nic.in"] = httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED]")
    web.page("https://raitamitra.karnataka.gov.in/raitha-siri", fixture("state_scheme.html"))
    tavily = FakeTavily({
        "national": [tav("https://www.myscheme.gov.in/schemes/kcc", "Kisan Credit Card | myScheme",
                         raw=("Kisan Credit Card scheme. Benefits: Short-term credit up to Rs. 3,00,000 at a "
                              "concessional interest rate of 4% per annum on prompt repayment for farmers. "
                              "Eligibility: All farmers, tenant farmers, oral lessees and sharecroppers are eligible "
                              "for the card. Documents required: Aadhaar card, land records and passport photo. "
                              "How to apply: Apply at the nearest bank branch with the filled application form."))],
        "state": [tav("https://raitamitra.karnataka.gov.in/raitha-siri", "Raitha Siri")],
        "ministry": [tav("https://pmkisan.gov.in", "PM-KISAN")],
    })
    snapshots: List[Dict[str, Any]] = []

    async def writer(**kw):
        snapshots.append(kw)
        return kw

    async def catalog():
        return CATALOG
    f, clock = make_fetcher(web)
    svc = LiveService(fetcher=f, reg=Registry(), client_factory=lambda: tavily, catalog_loader=catalog,
                      snapshot_writer=writer)
    return svc, tavily, snapshots, clock


async def run_live(svc, db, question="pm kisan crop insurance credit", state="Karnataka"):
    t0 = time.monotonic()
    d = await svc.discover(topic_keywords(question), state, "ragi")
    return await svc.verify(d, db, started=t0, deadline=t0 + settings.LIVE_BUDGET_SECONDS,
                            started_at=datetime.now(timezone.utc), question=question)


class TestService:
    @pytest.mark.asyncio
    async def test_query_triggers_discovery_retrieval_verification_with_provenance(self, live):
        svc, tavily, snapshots, _ = live
        db = [stored("PM_KISAN", "Rs. 6,000 per year", ["Aadhaar Card", "Land Records"], "https://pmkisan.gov.in"),
              stored("PMFBY", "premium 2%", ["Aadhaar Card", "Bank Passbook"], "https://pmfby.gov.in"),
              stored("MGNREGA", None, None, "https://nrega.nic.in")]
        out = await run_live(svc, db)
        assert len(tavily.calls) == 4                                       # live search, several domains
        f = out.freshness
        assert f["PM_KISAN"]["status"] == LIVE_VERIFIED
        assert {"benefit_amounts", "documents", "application_url"} <= set(f["PM_KISAN"]["verified_fields"])
        assert f["PM_KISAN"]["fields"]["benefit_amounts"]["status"] == CONFIRMED
        src = f["PM_KISAN"]["sources"][0]
        assert src["url"].startswith("https://pmkisan.gov.in") and src["retrieved_at"] and src["checked_at"]
        assert src["method"] == "direct" and src["http_status"] == 200
        # myScheme page is JavaScript-built: its text came through Tavily during this search, and says so
        assert f["KCC"]["status"] == LIVE_VERIFIED and f["KCC"]["sources"][0]["method"] == "tavily"
        assert "via Tavily" in f["KCC"]["label"]
        # PMFBY: page says closed while stored says active → conflict kept, stored record untouched
        assert f["PMFBY"]["status"] == LIVE_VERIFIED
        assert {c["field"] for c in f["PMFBY"]["conflicts"]} >= {"application_status"}
        assert any(c.scheme_id == "PMFBY" and c.field == "application_status" for c in out.conflicts)
        # unreachable source: stored information, with the reason and the stored date
        assert f["MGNREGA"]["status"] == NOT_VERIFIED and "certificate" in f["MGNREGA"]["label"]
        assert "2026-09-26" in f["MGNREGA"]["label"]
        # unmatched official scheme page = new discovery, shown as such (not as verified stored data)
        r = out.report
        assert r["new_discoveries"] == [{"name": "Raitha Siri - Karnataka Farmer Income Support",
                                         "url": "https://raitamitra.karnataka.gov.in/raitha-siri"}]
        assert set(r["hosts_accessed"]) >= {"pmkisan.gov.in", "pmfby.gov.in", "myscheme.gov.in",
                                            "raitamitra.karnataka.gov.in"}
        assert r["sources_failed"] == 1 and "Other government websites were not checked" in r["coverage_note"]
        assert any("couldn't be read" in w for w in r["warnings"])
        # provenance snapshots for every page actually retrieved
        recorded = {s["canonical"] for s in snapshots}
        assert canonical_url("https://pmkisan.gov.in") in recorded and canonical_url("https://nrega.nic.in") in recorded
        assert next(s for s in snapshots if "pmkisan" in s["canonical"])["fields"]["benefit_amounts"]["evidence"]

    @pytest.mark.asyncio
    async def test_cached_results_are_never_labelled_live(self, live):
        svc, _, _, clock = live
        db = [stored("PM_KISAN", "Rs. 6,000 per year", ["Aadhaar Card"], "https://pmkisan.gov.in")]
        first = await run_live(svc, db)
        assert first.freshness["PM_KISAN"]["status"] == LIVE_VERIFIED
        second = await run_live(svc, db)                                    # within the refresh policy
        f = second.freshness["PM_KISAN"]
        assert f["status"] == CACHED and "not re-checked now" in f["label"] and f["verified_fields"] == []
        assert "pmkisan.gov.in" not in second.report["hosts_accessed"]

    @pytest.mark.asyncio
    async def test_search_failure_falls_back_with_an_explicit_warning(self, live, monkeypatch):
        svc, tavily, _, _ = live
        tavily.fail = {"national", "ministry", "state", "open"}
        db = [stored("PM_KISAN", "Rs. 6,000 per year", ["Aadhaar Card"], "https://pmkisan.gov.in")]
        out = await run_live(svc, db)
        assert out.report["discovery"]["status"] == "FAILED"
        assert any("search failed" in w for w in out.report["warnings"])
        assert out.freshness["PM_KISAN"]["status"] == LIVE_VERIFIED       # stored official page still re-checked

    @pytest.mark.asyncio
    async def test_nothing_reachable_says_so(self, live, web, monkeypatch):
        svc, tavily, _, _ = live
        tavily.by_group = {}
        web.routes["https://pmkisan.gov.in"] = httpx.ConnectError("refused")
        out = await run_live(svc, [stored("PM_KISAN", None, None, "https://pmkisan.gov.in")])
        assert out.report["sources_accessed"] == 0
        assert any("No official source could be read" in w for w in out.report["warnings"])

    @pytest.mark.asyncio
    async def test_page_cap_and_time_budget(self, live, web, monkeypatch):
        svc, tavily, _, _ = live
        monkeypatch.setattr(settings, "LIVE_MAX_SOURCES", 2)
        out = await run_live(svc, [stored("PM_KISAN", None, None, "https://pmkisan.gov.in")])
        assert sum(1 for s in out.report["sources"] if s["status"] == "NOT_CHECKED") >= 1
        monkeypatch.setattr(settings, "LIVE_MAX_SOURCES", 8)

        def hang(request):
            time.sleep(0.4)
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"late")
        web.routes["https://pmfby.gov.in"] = hang
        t0 = time.monotonic()
        d = await svc.discover("", "Karnataka", None)
        res = await svc.verify(d, [stored("PMFBY", None, None, "https://pmfby.gov.in")], started=t0,
                               deadline=t0 + 0.05)
        pmfby = next(s for s in res.report["sources"] if "pmfby" in s["url"])
        assert pmfby["status"] in (fx.TIMEOUT, fx.SKIPPED_CRAWL_DELAY) and time.monotonic() - t0 < 5


# ─── the retrieval step end to end (a user query triggers it) ────────────────

class TestRetrievalStep:
    @pytest.mark.asyncio
    async def test_user_query_returns_source_backed_results(self, live, monkeypatch):
        """A scheme question → live discovery on several official domains → pages fetched and verified →
        merged results carry source links, retrieval timestamps and freshness labels; stored-only schemes
        say they weren't re-checked; the eligibility engine still decides eligibility from stored rules."""
        svc, tavily, _, _ = live
        import app.agents.retrieval_agent as agent
        import app.live.service as service_module
        monkeypatch.setattr(settings, "LIVE_VERIFICATION_ENABLED", True)
        monkeypatch.setattr(service_module, "live_service", svc)
        db = [stored("PM_KISAN", "Rs. 6,000 per year", ["Aadhaar Card"], "https://pmkisan.gov.in"),
              stored("PMFBY", "premium 2%", ["Aadhaar Card"], "https://pmfby.gov.in"),
              stored("ENAM", "Online market", None, "https://enam.gov.in")]

        async def fake_db(request):
            return db

        async def fake_graph(request):
            return []
        monkeypatch.setattr(agent, "search_db", fake_db)
        monkeypatch.setattr(agent, "search_graph", fake_graph)
        monkeypatch.setattr(settings, "LIVE_DIRECT_FETCH_SCHEMES", 2)
        state = {"profile": {"state": "Karnataka", "primary_crop": "ragi"},
                 "contextual_query": "PM Kisan and crop insurance schemes", "query_intent": "scheme_search"}
        out = await agent.retrieval_agent_node(state)
        cands = {c["scheme_id"]: c for c in out["merged_candidates"]}
        pk = cands["PM_KISAN"]
        assert pk["freshness"]["status"] == LIVE_VERIFIED
        assert any(s["type"] == "LIVE_WEB" and s["url"].startswith("https://pmkisan.gov.in") for s in pk["sources"])
        assert pk["freshness"]["sources"][0]["retrieved_at"]
        assert cands["ENAM"]["freshness"]["status"] == STORED                       # not checked: says so
        assert "not checked" in cands["ENAM"]["freshness"]["label"] or "wasn't checked" in cands["ENAM"]["freshness"]["label"]
        assert out["live_check"]["performed"] and out["live_check"]["sources_accessed"] >= 2
        assert any(c["field"] == "application_status" for c in out["source_conflicts"])   # → human review
        assert "raitamitra.karnataka.gov.in" in out["live_check"]["hosts_accessed"]
        # the deterministic note in the reply never claims more than was checked
        from app.agents.response_formatter import live_check_note
        note = live_check_note(out["live_check"], [{"name": "PM-KISAN", "freshness": pk["freshness"]},
                                                   {"name": "e-NAM", "freshness": cands["ENAM"]["freshness"]}])
        assert "Checked live on official websites just now" in note and "not re-checked" in note


def test_extraction_stays_fast_on_huge_search_texts():
    """Real Tavily results carried 540k–700k characters; extraction took 20–40 s (regex rescans). Now linear + capped."""
    worst = ("farmers with land holdings and income below limits may apply for support " * 8000)    # no full stops
    t = time.monotonic()
    ex = extract(text=worst + " Eligibility: Farmers with up to 2 hectares of land.")
    assert time.monotonic() - t < 3
    assert ex.fields["land_requirement"].value                          # still found
    assert extract(text="Farmers holding up to 0.5 hectare. Income below Rs. 2 lakh.").fields[
        "land_requirement"].value == ["Farmers holding up to 0.5 hectare"]


def test_xml_declared_pages_parse_and_bad_pages_fail_alone():
    html = '<?xml version="1.0" encoding="utf-8"?>' + fixture("state_scheme.html")
    assert extract(html=html).fields["name"].value.startswith("Raitha Siri")


@pytest.mark.asyncio
async def test_ministry_name_alone_is_not_live_verification(live, web):
    svc, tavily, _, _ = live
    web.page("https://pmkisan.gov.in", "<html><body><h1>PM-KISAN</h1><p>Administered by the Ministry of "
                                       "Agriculture and Farmers Welfare.</p></body></html>")
    tavily.by_group = {}
    out = await run_live(svc, [stored("PM_KISAN", "Rs. 6,000 per year", ["Aadhaar Card"], "https://pmkisan.gov.in")])
    assert out.freshness["PM_KISAN"]["status"] == SOURCE_REACHABLE


@pytest.mark.asyncio
async def test_one_unparseable_page_does_not_abort_the_check(live, monkeypatch):
    svc, _, _, _ = live
    import app.live.service as service_module
    real = service_module.extract

    def flaky(**kw):
        if "pmfby" in (kw.get("base_url") or ""):
            raise ValueError("unparseable")
        return real(**kw)
    monkeypatch.setattr(service_module, "extract", flaky)
    db = [stored("PM_KISAN", "Rs. 6,000 per year", ["Aadhaar Card"], "https://pmkisan.gov.in"),
          stored("PMFBY", "premium 2%", ["Aadhaar Card"], "https://pmfby.gov.in")]
    out = await run_live(svc, db)
    assert out.freshness["PM_KISAN"]["status"] == LIVE_VERIFIED
    assert out.freshness["PMFBY"]["status"] != LIVE_VERIFIED


@pytest.mark.asyncio
async def test_stored_scheme_pages_come_before_discovered_reports_and_listings(live, monkeypatch):
    """Real searches returned annual reports and portal listings that used every slot (no scheme verified)."""
    svc, tavily, _, _ = live
    monkeypatch.setattr(settings, "LIVE_MAX_SOURCES", 2)
    tavily.by_group = {"national": [tav(f"https://agriwelfare.gov.in/Documents/report_{i}.pdf") for i in range(5)] +
                       [tav("https://services.india.gov.in/service/listing?cat_id=12&page_no=3")]}
    out = await run_live(svc, [stored("PM_KISAN", "Rs. 6,000 per year", ["Aadhaar Card"], "https://pmkisan.gov.in")])
    assert out.freshness["PM_KISAN"]["status"] == LIVE_VERIFIED                   # its official page got a slot
    urls = [s["url"] for s in out.report["sources"]]
    assert not any("listing" in u for u in urls)                                 # listing pages dropped
    r = out.report
    assert r["sources_not_checked"] == 4 and r["sources_failed"] == 1            # cap ≠ failure (report_0 404s)
    assert any("not checked (limit of 2 pages" in w for w in r["warnings"])


def test_direct_checks_go_to_schemes_serving_the_stated_need():
    from app.live.service import prioritise
    db = [RetrievalResult(source_type=SourceType.DATABASE, scheme_id=sid, title=title, description=desc)
          for sid, title, desc in [("AGMARKNET", "Agricultural Marketing Information Network", "market prices"),
                                   ("ATMA", "Agricultural Technology Management Agency", "extension"),
                                   ("PMFBY", "Pradhan Mantri Fasal Bima Yojana", "crop insurance against loss"),
                                   ("PM_KISAN", "Pradhan Mantri Kisan Samman Nidhi", "income support")]]
    order = [r.scheme_id for r in prioritise(db, "need crop insurance for cotton", {})]
    assert order[0] == "PMFBY"
    catalog = {"PM_KISAN": {"name": "Pradhan Mantri Kisan Samman Nidhi", "short_name": "PM-KISAN",
                            "aliases": ["PM Kisan"]}}                       # aliases come from the stored catalog
    assert [r.scheme_id for r in prioritise(db, "tell me about PM Kisan and crop insurance", catalog)][:2] == \
        ["PM_KISAN", "PMFBY"]
