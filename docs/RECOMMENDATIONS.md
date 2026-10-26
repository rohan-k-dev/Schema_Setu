# Eligible Schemes and Relevant Alternatives

Scheme answers now have two clearly separated parts:

| Section | What is in it | Decided by |
|---|---|---|
| **A. Eligible Schemes** | Only schemes the deterministic eligibility engine marks `ELIGIBLE` (every required published criterion matches the farmer's details). Unchanged rules, unchanged order. Each card says what still needs the department's confirmation. | `app/eligibility/` (unchanged) |
| **B. More Relevant Schemes & Alternatives** | Other evaluated schemes that may help — ranked by relevance, each with the reason, what still needs checking, the official link and the last verification date. **Eligibility is not confirmed** for any of them. | `app/recommendation/alternatives.py` |
| *(collapsed)* Schemes that don't match | Known mismatches with no relation to the farmer's need, still visible with the reason. | same |

Relevance never changes an eligibility decision, never turns missing data into a match, and never creates
eligibility rules.

## Statuses

| Internal status | From the engine | Shown as |
|---|---|---|
| `CONFIRMED_ELIGIBLE` | `ELIGIBLE` | Section A |
| `ADDITIONAL_INFORMATION_REQUIRED` | `NEEDS_MORE_INFORMATION` | "Not confirmed — more information needed" + the missing details |
| `ELIGIBILITY_UNCONFIRMED` | `UNVERIFIABLE`, scheme has no structured rules | "Not confirmed — check the official criteria" + published criteria text |
| `SCHEME_INFORMATION_INCOMPLETE` | `UNVERIFIABLE` with conflicting rules, or a record awaiting review | "Not confirmed — scheme details incomplete" |
| `KNOWN_MISMATCH` | `NOT_ELIGIBLE` | "Doesn't match a published criterion" + which one (e.g. *age: requires 18–40, you have 61*). In Section B only when it serves the farmer's stated need or the same purpose as an eligible scheme; otherwise collapsed. |

## Relevance ranking (deterministic, explainable)

Signals — all from stored scheme records and the farmer's own question / profile:

- **Assistance categories** of each scheme (crop insurance, credit, irrigation, machinery, seeds / fertiliser / soil,
  organic, horticulture, livestock, fisheries, income support, pension, markets, storage, training, livelihood,
  housing, FPOs, solar, crop production), derived from the stored name, description, benefits and type.
  A scheme's **primary purpose** is what its name / type / benefit type says.
- **Stated need:** the same categories found in the question or occupation ("dairy cattle support" → livestock).
- **Similar purpose** to a scheme in Section A (shared primary category).
- **Targeting:** state-specific scheme for the farmer's state; crop-specific scheme for their crop.
- **Profile signals named in the stored text:** small and marginal farmers (land ≤ 2 ha), women farmers.
- **Criteria already met** (rules the engine found satisfied).

Tiers, in the required order: **1** strongly related (stated need, state/crop targeting or criteria met) with
eligibility not yet confirmed → **2** same need / similar purpose (incl. a meaningful known mismatch, ranked
lower) → **3** other schemes available in the farmer's state. Within a tier: score, then scheme id. The UI shows
5 at a time ("Show more").

## Coverage and duplicates

- Every scheme applicable to the farmer's state is now evaluated (`MAX_DB_RESULTS` / `MAX_CANDIDATES` /
  `MAX_RESPONSE_SCHEMES` 25 → 60). Before, the list was cut at 25 **alphabetically** after targeting, so 6–13
  applicable schemes per profile were never evaluated or shown.
- A scheme is shown once: records flagged `possible_duplicate`, and records whose normalised name equals another
  one's, are hidden; the canonical record (not flagged, eligible, has rules) is the one kept. The corpus keeps the
  planted test duplicate `PMKISAN_MAN_DHAN` (evaluation case GQ_011 checks the flag) — farmers no longer see it.

## API

`POST /chat` → each item of `schemes` gains `recommendation_section`, `recommendation_status`, `status_text`,
`relevance {tier, score, rank, reasons, categories, similar_to, matched_needs}`, `conditions_to_verify`,
`mismatches`, `application_url`, `last_verified_at`, `applicable_states`, `level`; the order is Section A (ranker
order) → B (relevance) → not matching. New `recommendation_summary {eligible, alternatives, not_matching,
stated_needs}`. Existing fields are unchanged, so older clients keep working (the UI falls back to one list when
no section tags are present). The reply text gains one deterministic sentence about the alternatives.

## Corpus expansion

`scripts/discover_missing_schemes.py` looks for genuinely missing schemes on official sites with the polite live
fetcher (robots.txt, rate limits, official hosts only, no access-control bypass), follows up to 4 of the
programme's own detail pages / guideline PDFs, and builds a candidate record only from what the pages state
(evidence kept in `source_records`, no eligibility rules, `needs_review`). Candidates go into
`data/incoming/` for the reviewed scheme-update pipeline (detect → admin approval → publish); nothing is added
directly. A candidate is refused when the page doesn't name the programme, states no description plus
eligibility / beneficiary benefits, says it's closed, or names an existing scheme or its component.

## Data-coverage report (measured 2026-10-26)

Database counts are from the Docker PostgreSQL corpus; per-profile counts from the pipeline on the canonical
corpus (`app/tests/recommendation_harness.py`, same nodes as `/chat`).

| | Before | After |
|---|---|---|
| Canonical schemes (DB) | 40 (all ACTIVE) | 40 — **no new scheme could be added** (below) |
| Schemes with structured eligibility rules | 22 (25 rules) | 22 (25 rules) |
| …all rules quoting official source text | 22 | 22 |
| Schemes without rules (never "eligible") | 18 | 18 |
| With official URL / application URL | 40 / 3 | 40 / 3 |
| With documents / application steps | 18 / 9 | 18 / 9 |
| State-specific / crop-specific | 7 / 3 | 7 / 3 |
| Duplicates | 1 planted duplicate shown to farmers | hidden from farmers (kept in corpus for GQ_011); 1 candidate (PDMC) detected as a component of PMKSY and not added |
| Schemes available for alternatives | — (one mixed list) | 39 (all active schemes except the hidden duplicate), filtered per state |

**Corpus expansion — sources actually checked (real network, from the backend container):** 18 official pages
for well-known programmes not in the corpus, 48 requests in total including detail pages and guideline PDFs
(`data/evaluation/reports/corpus_expansion_2026-10-26.json`).

| Result | Programmes |
|---|---|
| Refused automated access (HTTP 403) — not bypassed | Rashtriya Gokul Mission, NPDD, AHIDF (dahd.gov.in), FIDF (dof.gov.in) |
| JavaScript-only pages | PMMSY, NBHM, PMFME, PM Kisan Sampada, Kisan Rin / MISS, RWBCIS |
| Unreachable / timed out | KALIA (Odisha), MMKAY (Jharkhand), Rythu Bima (Telangana); RGKNY (Chhattisgarh) timed out |
| Readable, but the home and detail pages state no description plus benefits / eligibility | NMNF, NMEO-OP, Meri Fasal Mera Byora (Haryana) |
| Readable, but a component of an existing scheme | PDMC = "Per Drop More Crop", already an alias of PMKSY (its extracted "benefits" were committee clauses of a circular) |
| **Added** | **0** |

**Per-profile results** (8 profiles × questions; before = the pipeline before this feature):

| Profile | Before: evaluated / eligible (one mixed list of 25) | After: evaluated / eligible / alternatives (tier 1/2/3) / not matching |
|---|---|---|
| Karnataka, ragi, 2 acres | 25 / 10 | 31 / 13 / 16 (0/4/12) / 1 |
| Maharashtra, cotton, land unknown | 25 / 6 | 31 / 9 / 20 (1/5/14) / 1 |
| Tamil Nadu, paddy, woman | 25 / 11 | 31 / 14 / 16 (0/6/10) / 0 |
| Uttar Pradesh, wheat, 30 acres, 61 | 25 / 7 | 32 / 11 / 20 (6/4/10) / 0 |
| Telangana, dairy farmer | 25 / 4 | 34 / 5 / 22 (1/3/18) / 6 |
| Assam, state only | 25 / 1 | 34 / 1 / 32 (0/1/31) / 0 |
| Andhra Pradesh, groundnut, 19 | 25 / 8 | 32 / 12 / 18 (1/5/12) / 1 |
| No state, mustard | 25 / 2 | 38 / 3 / 33 (6/1/26) / 1 |

More eligible schemes appear **only because more applicable schemes are now evaluated**; every decision for a
scheme that was evaluated before is identical (`test_every_decision_equals_the_pre_feature_baseline`).

## Tests

- `app/tests/test_recommendation_sections.py` (19): decisions identical to the pre-feature baseline
  (`fixtures/recommendations/baseline_statuses.json`, 8 profiles); Section A = engine ELIGIBLE set in ranker order;
  alternatives returned when not eligible; tier/score order and ranks; missing information ≠ mismatch;
  NOT_ELIGIBLE never eligible and only a meaningful alternative; duplicates across sections; state / crop
  targeting; stored links and dates never invented; profile without state; API summary; unit cases for tiers,
  need vs similarity, honest statuses, duplicate by name / flag, empty input.
- `app/tests/test_corpus_discovery.py` (8): records only from page content, no rules, missing fields empty,
  governance clauses rejected as benefits, components / aliases detected as duplicates, seeds official.
- `scripts/ui_alternatives_test.py`: real pipeline on the real PostgreSQL corpus in the backend container, shown
  in the browser — sections, reasons, statuses, links, "Show more", collapsed group, empty state, phone width.

### Actual results (2026-10-26)

| Suite | Result |
|---|---|
| Backend (`py -m pytest app/tests`) | **1282 passed**, 70 skipped (opt-in PostgreSQL) — 27 new |
| PostgreSQL integration (all `*_pg.py`) | **70 passed** |
| Browser: `scripts/ui_alternatives_test.py` (real pipeline, real PostgreSQL corpus; only the LLM wording bypassed) | **22/22** — Telangana dairy farmer: 34 evaluated, 5 eligible, 22 alternatives, 6 not matching |
| Browser: `scripts/ui_live_check_test.py` (unsectioned fallback list) | **22/22** |
| Evaluation runners (offline) | eligibility 104/104 scheme-level, 0 false positives / 0 false negatives; recommendation 7/7; e2e 24/24; human review 23/23; adversarial 35/36 (A31: known fake secrets in `test_admin_ops.py`) |
| Frontend | `tsc --noEmit` and `npm run build` clean |

Offline tests use the canonical corpus file and mocks; the live-source statements above come only from the
real-network discovery run.

## Limitations and remaining work

- **No new schemes were added**: the official sites for the missing programmes were blocked, JavaScript-only or
  unreachable for a polite fetcher. Options: a real `TAVILY_API_KEY` (search results carry page text for
  JavaScript sites), myScheme's official API (needs their key), or a person entering records from official
  guideline PDFs through the scheme-update pipeline.
- 18 of 40 schemes have no structured eligibility rules, so they can only ever be alternatives. Encoding their
  official criteria (with source text) through the reviewed pipeline would move eligible ones into Section A.
- Category tagging is keyword-based on stored text; unusual wording can miss or add a category (reasons are shown
  so a wrong one is visible).
- Relevance uses stored data only; a farmer's district isn't used (no district-level data in the corpus).
- **Found, not changed (strict engine untouched):** the occupation rule compares exactly, so "dairy farmer" does
  not satisfy `occupation = farmer` (PM-KISAN and DEDS show as mismatches for a dairy farmer). Whether a
  sub-type of farmer should match is an eligibility-normalisation decision for a reviewed change.
