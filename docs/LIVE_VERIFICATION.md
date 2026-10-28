# Real-Time Scheme Discovery and Verification

Every scheme question now runs a **query-time check of official government websites** in addition to
SchemeSetu's stored scheme database. The farmer sees, per scheme, whether its details were read live on an
official site during this question, re-used from an earlier read, or come from stored records, and why. It
also shows the source link and the retrieval time.

Eligibility is **still decided only by the deterministic rules engine** on stored, reviewed rules. Live text is
shown as evidence and compared field by field. The LLM never invents rules, amounts, deadlines or links, and live
pages never silently change stored records.

## Flow

```
question ──► retrieval_agent_node
               ├─ stored DB search ─┐
               ├─ knowledge graph  ─┤
               └─ live discovery ───┤  (Tavily; several official domain groups in parallel)
                                    ▼
                   LiveService.verify  (time budget LIVE_BUDGET_SECONDS, ≤ LIVE_MAX_SOURCES pages)
                     targets = discovered official pages + stored official URLs of the top schemes
                     ├─ polite fetch (robots.txt, rate limit, cache) ─► extract fields ─► verify vs stored
                     ├─ provenance snapshot (live_source_snapshots, last known-good kept)
                     └─ per-scheme freshness + report ─► merged candidates, source conflicts → human review
                                    ▼
             eligibility (stored rules) ─► ranking ─► response (+ freshness, + live_check, deterministic note)
```

| Module | Role |
|---|---|
| `app/live/sources.py` | Official-source registry: national portals, ministry sites, state portals per state, `.gov.in` / `.nic.in`; classification by parsed hostname (no substring tricks); refresh policy per source. |
| `app/live/discovery.py` | Live search with Tavily: one search per domain group (national, ministry, state of the farmer) plus an open search; non-official results dropped; duplicates merged by canonical URL. |
| `app/live/fetcher.py` | Polite fetcher with a cache (below). HTML and PDF (pypdf). |
| `app/live/extractor.py` | Deterministic field extraction (headings, JSON-LD, lists, amounts, dates, status, ministry, official application links), each field with its evidence text. |
| `app/live/verifier.py` | Field comparison with stored records: CONFIRMED / CONFLICT / LIVE_ONLY / STORED_ONLY / EVIDENCE_ONLY. |
| `app/live/service.py` | Orchestration, time budget, scheme matching, freshness labels, report. |
| `app/database/repositories/live_snapshot_repository.py` | Provenance and change detection (migration 0011). |
| `GET /admin/ops/live-sources` | Admin view of snapshots (`?change_status=` filter). |

## Fields extracted

name, description, eligibility, exclusions, benefits, benefit amounts, income requirement, land requirement,
documents, application process, application URL (official hosts only), important dates, open / closed status,
ministry. Every source also carries its URL, HTTP status, method (direct read or search-service text),
`retrieved_at` (when the content was obtained) and `checked_at`. A field that a page does not state is **absent**;
it is never filled in.

## Freshness labels (per scheme)

| Status | Meaning | Shown as |
|---|---|---|
| `LIVE_VERIFIED` | An official page was read during **this** question and scheme details were extracted. | "Verified live", with the fields found and which match the stored record |
| `CACHED` | Read earlier within the refresh policy and re-used; **not** re-checked now. Keeps its original time. | "Checked earlier (not re-checked now)" |
| `SOURCE_REACHABLE` | Site reached, but no scheme details readable (JavaScript-only page, homepage, …). | "Stored details — page reached, not readable" + reason |
| `NOT_VERIFIED` | The official source could not be read (TLS failure, 403, timeout, robots.txt, CAPTCHA, …). | "Stored details — couldn't check now" + reason + stored date |
| `STORED` | Not checked for this question (page cap / time budget / no official URL). | "Stored details — not checked live" + stored date |

A response-level `live_check` report lists every source tried with its status and reason, the hosts actually
read, counts, new official pages discovered (shown as such, never run through the rules), warnings (search not
configured or failed; sources unreadable; nothing readable), and a coverage note: *"Other government websites
were not checked for this question."* Cached information is never labelled live, and the system never claims
that every government site was checked.

## Respecting sites

- **robots.txt** is fetched and honoured per host (RFC 9309, user agent `SchemeSetuBot/1.0`); `Crawl-delay` is
  respected. A page whose delay would exceed the question's time budget is skipped (`SKIPPED_CRAWL_DELAY`).
- **Rate limit:** one request at a time per host, at least `LIVE_HOST_MIN_INTERVAL` seconds apart.
- **Access controls are never bypassed:** 401/403/429 → `ACCESS_DENIED`; CAPTCHA pages → `CAPTCHA`; login
  forms → `AUTH_REQUIRED`; JavaScript-only pages → `JS_REQUIRED`. No retries, no header tricks, no headless
  rendering, no TLS verification bypass (`TLS_ERROR` is reported instead).
- Redirects are followed only to official hosts; size (`LIVE_MAX_BYTES`), type (HTML / PDF / text) and
  per-request timeout limits apply. Only official hosts are fetched at all.
- **Cache:** national portals 12 h, ministry / state 24 h, PDFs 7 days; afterwards revalidated with
  `ETag` / `Last-Modified` (`304` → `NOT_MODIFIED`, counts as a fresh check). Failures are cached for 30 min so
  sites are not hammered.

## Provenance and change detection (`live_source_snapshots`)

Per canonical URL: last attempt (status, HTTP status, time, extracted fields, quality), the **last known-good**
extraction with its hash and time, the **previous** good version, and a change status:

| Change | When | Last known-good |
|---|---|---|
| `NEW` | first good read | set |
| `UNCHANGED` | same content hash | kept |
| `UPDATED` | different content, no loss of fields or quality | replaced; old one kept as `previous_good` |
| `INCOMPLETE` | fewer fields or lower quality than the last good | **kept** (a worse read never overwrites) |
| `UNPARSEABLE` | readable but no scheme fields | kept |
| `MISSING` | 404 / 410 | kept |
| `FAILED` | any other failure | kept |

`duplicate_of` marks the same content under another URL. Conflicts with stored records (amounts, documents,
open/closed status) are also raised as source conflicts, so the case goes to **human review**; stored records
and rules change only through the reviewed scheme-update pipeline (docs/SCHEME_UPDATES.md).

## Privacy

Tavily receives only fixed topic words found in the question (from a fixed list: insurance, loan, irrigation, …),
the farmer's state and main crop, and fixed words. It never receives the question text, age, category or
income. Official pages are fetched by the server; those sites see the server, not the farmer (docs/PRIVACY.md).

## Configuration (`backend/.env`)

| Variable | Default | |
|---|---|---|
| `LIVE_VERIFICATION_ENABLED` | `true` | turn the query-time check off (falls back to the earlier snippet-only web search) |
| `LIVE_BUDGET_SECONDS` | `9` | time budget per question (discovery gets 60 %) |
| `LIVE_MAX_SOURCES` | `8` | pages per question; the rest are reported `NOT_CHECKED` |
| `LIVE_DIRECT_FETCH_SCHEMES` | `4` | top stored schemes whose official page is re-checked directly |
| `LIVE_TAVILY_RESULTS` | `5` | results per search |
| `LIVE_FETCH_TIMEOUT` / `LIVE_MAX_BYTES` / `LIVE_HOST_MIN_INTERVAL` | `6` / `3000000` / `1.0` | per-request limits |
| `TAVILY_API_KEY` | — | required for discovery of new pages; without it only stored official URLs are re-checked |

## Tests

- `app/tests/test_live_verification.py` (32 tests, saved fixtures in `app/tests/fixtures/live/`, a generated PDF,
  `httpx.MockTransport`, a fake Tavily client): registry, multi-domain discovery and merging, privacy of the
  search query, not-configured / partial / timed-out searches, robots.txt, 403/429/404/503/timeout/TLS/DNS,
  CAPTCHA / login / JavaScript shell, redirects, size/type/official limits, cache freshness, ETag revalidation,
  failure cache, rate limit and crawl-delay, field extraction with evidence, missing fields, conflicting fields,
  closed status, the provenance rule, service freshness labels, Tavily-content method, conflicts, new discoveries,
  page cap and time budget, cached-never-live, search-failure fallback, and the retrieval step end to end
  (a query → live discovery → verified results with source links and timestamps).
- `app/tests/test_live_snapshot_pg.py` (PostgreSQL): NEW / UNCHANGED / UPDATED keeps the previous good version;
  INCOMPLETE / UNPARSEABLE / MISSING / FAILED keep the last known-good; duplicates; admin listing.
- `scripts/live_check.py "question" --state S [--crop C] [--json out.json]` — the **real network** run.
- `scripts/ui_live_check_test.py` — runs the real retrieval step in the backend container, then checks the
  browser display of that real result (22 checks).

## Real-network results (2026-10-26, from the backend container)

These are actual runs, not mocks. With the configured keys, the Tavily key is a placeholder, so **discovery of
new pages did not run**: only stored official URLs were re-checked directly.

| Source | Result |
|---|---|
| agriinfra.dac.gov.in (Agriculture Infrastructure Fund) | **Read live** — eligibility, benefits, amounts, application process, application link extracted → `LIVE_VERIFIED` |
| nsmny.mahait.org, raitamitra.karnataka.gov.in | Reached (HTTP 200) but the pages are homepages without scheme details → `SOURCE_REACHABLE` |
| agmarknet.gov.in, pmfby.gov.in, agriwelfare.gov.in | JavaScript-only pages → `JS_REQUIRED` |
| pmkisan.gov.in, jansuraksha.gov.in | TLS certificate chain does not verify → `TLS_ERROR` (verification is not disabled) |
| india.gov.in | HTTP 403 → `ACCESS_DENIED` (not bypassed) |
| myscheme.gov.in | JavaScript shell; scheme content needs their keyed API (not used) |
| agricoop.nic.in | Not reachable (DNS / timeout) — a stored official URL that appears dead |

## Real-network results with Tavily (2026-10-26)

With a real Tavily key all four domain-group searches ran (some timed out within their 60 % share of the budget →
`PARTIAL`). Examples: "crop insurance for cotton" (Maharashtra) → myScheme pages through Tavily, india.gov.in,
agriinfra.dac.gov.in read directly; PMFBY's own site is JavaScript-only (honestly "page reached, not readable").
"pm kisan income support" (Karnataka) → agriwelfare.gov.in compendium PDF and pib.gov.in read; pmkisan.gov.in
TLS failure; raitamitra timeout. Stored URL of the Tamil Nadu scheme returns 404. A live check now takes
≈ 5–8 s (it took 72 s before the extraction fix).

## Limitations

- Discovery searches can time out within their share of the 9 s budget (reported as `PARTIAL`).
- Many search results are multi-scheme reports or portal pages; only 8 pages are read per question.
- Many official portals are JavaScript-only or block automated reads. Through Tavily their text can still
  arrive (method "tavily", labelled *via Tavily*); without it they stay "stored".
- Field extraction is heuristic (headings, lists, patterns); free-form pages may yield partial results, which are
  labelled and never replace a better stored or last-known-good value.
- The fetch cache is in memory per backend process (snapshots in PostgreSQL are durable).
- Stored URLs that are dead (agricoop.nic.in) should be corrected through the scheme-update pipeline.
- Live checks add up to `LIVE_BUDGET_SECONDS` to a scheme question.
