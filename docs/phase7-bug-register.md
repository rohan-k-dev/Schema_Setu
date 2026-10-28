# Phase 7 — Bug Register

Every defect found during Phase 7 evaluation, with root cause, fix and the regression test that guards it.
Regression tests live in `backend/app/tests/test_phase7_regressions.py` (named `test_bugNNN_*`).
"Detected by" points to the baseline run `data/evaluation/reports/before/` unless stated otherwise.

Severity scale (§136): **CRITICAL** = false eligibility / system unusable · **HIGH** = data leakage, broken core
journey, security · **MEDIUM** = wrong behaviour with a safe outcome · **LOW** = cosmetic / hygiene.

| ID | Component | Severity | Summary | Status |
|---|---|---|---|---|
| BUG-001 | Environment / API | CRITICAL | Backend could not import; API tests silently skipped | FIXED |
| BUG-002 | Eligibility | CRITICAL | Group names containing "or" treated as OR → false ELIGIBLE | FIXED |
| BUG-003 | Eligibility | CRITICAL | Negative / NaN / infinite numeric strings accepted → false ELIGIBLE | FIXED |
| BUG-004 | Profile / Eligibility | HIGH | `occupation`, `age` dropped; `has_land` never derived → core schemes stuck at NEEDS_MORE_INFORMATION | FIXED |
| BUG-005 | Human review | HIGH | Escalation never wired into the pipeline; real UNVERIFIABLE results never escalated | FIXED |
| BUG-006 | Retrieval | HIGH | Alphabetical truncation before eligibility dropped targeted schemes (recall@10 = 0.25) | FIXED |
| BUG-007 | Knowledge Graph | HIGH | Graph proposed schemes restricted to other crops/states (13 false relationships) | FIXED |
| BUG-008 | Retrieval | MEDIUM | Channel failures swallowed; outages indistinguishable from "no results" | FIXED |
| BUG-009 | Retrieval (Tavily) | MEDIUM | Tavily `url`/`title` dropped → no web source URLs, trust always UNKNOWN | FIXED |
| BUG-010 | Retrieval | LOW | Web identity map used `KUSUM`, corpus uses `PM_KUSUM` → duplicate candidate | FIXED |
| BUG-011 | Retrieval | LOW | Empty query + empty profile returned the whole catalogue | FIXED |
| BUG-012 | API contract / Frontend | HIGH | Scheme cards never carried documents, steps, source URL or graph evidence | FIXED |
| BUG-013 | XAI / Security | CRITICAL | LLM reply not validated: false eligibility, invented URL/amount/scheme reached the user | FIXED |
| BUG-014 | XAI | MEDIUM | Explanation validator rejected only 20% of fabrications and wrongly rejected a genuine OR explanation | FIXED |
| BUG-015 | XAI / Provenance | MEDIUM | Rule-level source URL never populated (provenance 0%) | FIXED |
| BUG-016 | Conversation | MEDIUM | With the LLM down every follow-up question asked about "farming land" | FIXED |
| BUG-017 | Profile | MEDIUM | No deterministic canonicalisation; invalid values stored | FIXED |
| BUG-018 | Conversation | MEDIUM | "the second one" not resolved deterministically; out-of-range ordinal not clarified | FIXED |
| BUG-019 | Recommendation | MEDIUM | Ties ordered by input order; graph-evidence boost never applied | FIXED |
| BUG-020 | Security | HIGH | Reviewer API key hard-coded in source | FIXED |
| BUG-021 | Privacy | HIGH | Full profile (income, category, Aadhaar status) and voice transcripts logged at INFO | FIXED |
| BUG-022 | Privacy | MEDIUM | Income/category/Aadhaar sent to Groq in prompts that do not need them | FIXED |
| BUG-023 | Security | MEDIUM | No message length limit (100 000 chars reached the LLM); blank messages accepted | FIXED |
| BUG-024 | Voice / Security | MEDIUM | Non-audio payload with an audio MIME type forwarded to the ASR provider | FIXED |
| BUG-025 | Performance / Stability | HIGH | Request cost grew linearly with the number of past sessions; memory never released | FIXED |
| BUG-026 | Security hygiene | LOW | f-string SQL (constant table names) in corpus importer | FIXED |
| BUG-027 | API contract | LOW | `CRITICAL_FIELDS` constant serialised as a profile field (and sent in the LLM tool schema) | FIXED |
| BUG-028 | API | LOW | `partial_results` reported when a healthy channel simply returned nothing | FIXED |
| BUG-029 | Evaluation data / Eligibility | MEDIUM | Golden label E26 wrong; categorical contradictory rules not detected | FIXED (dataset v2 + engine) |
| BUG-030 | Eligibility | LOW | "1.5 lakhs" / "lac" not parsed | FIXED (with BUG-003) |
| BUG-031 | Frontend / Session | HIGH | UI sent constant `default_session`; backend replaced it per request → every UI message was a new session | FIXED |
| BUG-032 | Frontend | HIGH | UI ignored `partial_results`, `no_results`, `clarification_required`, `scheme_details` and replaced real replies with "I found N schemes" | FIXED |
| BUG-034 | Conversation / Retrieval | MEDIUM | Follow-up about one scheme returned other graph matches too, replacing the list the user referred to | FIXED |
| BUG-035 | API / Ops | LOW | `/health` discarded graph status; `/health/ready` never set `graph_ready`; versions hard-coded (0.1.0 / 0.4.0 / 0.6.0) | FIXED |
| BUG-033 | Accessibility | LOW | `<html lang>` fixed to `en`; TTS audio not stoppable; 32 px expand button; few focus styles; land = 0 shown as "Not set" | FIXED |

Open items found but **not** fixed in Phase 7 are listed in `docs/phase7-limitations.md` (they are
limitations or out of scope, not defects with a safe fix).

---

## Detailed records

### BUG-001 — Backend could not import (CRITICAL)
- **Reproduction:** `python -c "from app.main import app"` → `TypeError: Reviver.__init__() got an unexpected keyword argument 'allowed_objects'`.
- **Root cause:** stray packages `langgraph-checkpoint 4.1.1` and `langgraph-prebuilt 1.1.0` (not in `requirements.txt`, nothing depends on them) were installed over the pinned `langgraph 0.0.31` and overwrote its `langgraph/checkpoint/` modules. The API tests caught the import error and **skipped** (4 skipped), so "388 passed" hid an unusable server.
- **How detected:** Phase 6 gate audit, importing the app directly.
- **Fix:** removed the two stray packages and force-reinstalled `langgraph==0.0.31` (environment). `test_api_health.py` no longer swallows the import error.
- **Prevention:** `test_bug001_app_imports_and_serves_health`; health tests now fail instead of skipping. Use a clean virtualenv from `requirements.txt` (documented in limitations / Phase 8).

### BUG-002 — OR-group substring match (CRITICAL, false eligibility)
- **Reproduction:** rules `land<=5`, `land>=1`, both in group `land_for_smallholders`; profile land = 9 → **ELIGIBLE** (expected NOT_ELIGIBLE). Case N08.
- **Root cause:** `evaluate_logical_groups` used `"OR" in group_name.upper()`, so any group name containing the letters "or" ("f**or**", "maj**or**") became an OR group.
- **Fix:** `is_or_group()` matches OR only as a name token (`OR`, `OR_x`, `x_or`). `backend/app/eligibility/logical.py`.
- **Test:** `test_bug002_*`. Baseline false-positive rate 2.86% → 0%.

### BUG-003 / BUG-030 — Numeric parsing (CRITICAL)
- **Reproduction:** rule `land<=5`, profile land `"-3"` → ELIGIBLE (A08). `"nan"` income → NOT_ELIGIBLE instead of unknown (A09). `"1.5 lakhs"` → unknown (A10).
- **Root cause:** `safe_parse_numeric` rejected negative *numbers* but not negative *strings*, accepted `nan`/`inf`, and only matched singular "lakh".
- **Fix:** single path for numbers and strings; reject negative and non-finite values; accept lakh/lakhs/lac/lacs/crore(s). `backend/app/eligibility/normalizer.py`.
- **Test:** `test_bug003_*`.

### BUG-004 — Profile fields required by corpus rules were dropped (HIGH)
- **Reproduction:** "I am a farmer from Karnataka with 2 acres growing ragi" → PM-KISAN, KCC, PMFBY, PMKSY, PM-KUSUM, SMAM, Soil Health Card, DEDS all **NEEDS_MORE_INFORMATION (occupation)** forever.
- **Root cause:** the extraction prompt asked for `occupation`, but `FarmerProfile` had no `occupation` (or `age`) field and `extra="ignore"` silently dropped it. PM-KISAN's `has_land` rule had no source, even though the user had stated their land size. Measured over 5 fully stated reference profiles × 40 schemes: 59 of 59 UNKNOWN outcomes came from unsupported fields (occupation 40, age 14, residence 5) plus 5 derivation gaps.
- **Fix:** `occupation` and `age` added to `FarmerProfile` and to the prompt. A documented derived-field policy: `has_land = land_size_acres > 0` (an explicit `has_land` value still wins). `backend/app/models/profile.py`, `backend/app/eligibility/evaluator.py`.
- **After:** NEEDS_MORE_INFORMATION rate for fully stated profiles 29.5% → 2.5%. The remainder is `residence` (MGNREGA), which no profile field captures; this is a documented data gap.
- **Test:** `test_bug004_*`.

### BUG-005 — Human review not connected (HIGH, Phase 6 gate failure)
- **Reproduction:** run any search that yields UNVERIFIABLE schemes → no review case (E2E20). `should_escalate([real UNVERIFIABLE EligibilityResult])` → `None`.
- **Root cause:** (1) `should_escalate` / `create_review_case` were never called outside unit tests; (2) `str(EligibilityStatus.UNVERIFIABLE)` is `"EligibilityStatus.UNVERIFIABLE"` on Python 3.11, so the comparison with `"UNVERIFIABLE"` was always false (the unit test used a fake string status); (3) rule conflicts also produce UNVERIFIABLE, so the RULE_CONFLICT reason was unreachable.
- **Fix:** `escalate_if_needed()` is called from the recommendation agent. It compares the enum value, checks conflicts first, and keeps one open case per session and reason. `needs_review` / `review_reason` / `review_case_id` are set in state, and a safe notice plus a `review` block are returned to the user. `backend/app/services/review_service.py`, `backend/app/agents/recommendation_agent.py`.
- **Test:** `test_bug005_*`, E2E20.

### BUG-006 — Relevant schemes truncated before eligibility (HIGH)
- **Reproduction:** Karnataka + ragi: STATE_KA_KRUSHAK and PM-KISAN absent from the 10 merged candidates (R01, E2E01).
- **Root cause:** the DB returned rows `ORDER BY name` and cut them at 10. The merger then sorted by source count and scheme ID and cut at 10 again, *before* eligibility. With about 30 nationally applicable schemes, state- or crop-specific schemes fell off alphabetically. Targeted recall@10 = 0.25.
- **Fix:** the DB retriever ranks state/crop-targeted schemes first, using batch-loaded targeting. The merger sorts by targeting first. Up to 25 candidates are evaluated (deterministic, cheap) and all evaluated results are returned, ranked by status. The LLM still sees only the top 10. `backend/app/retrieval/db_retriever.py`, `merger.py`, `core/config.py`.
- **Test:** `test_bug006_*`, retrieval runner.

### BUG-007 — Graph false relationships (HIGH)
- **Reproduction:** Karnataka + ragi graph candidates include NFSM / NMOOP / MIDH (crop-restricted to other crops).
- **Root cause:** `find_candidates_for_profile` took the *union* of dimension matches. Nationally applicable but crop-restricted schemes entered through the state dimension.
- **Fix:** exclude schemes whose state or crop restriction excludes the user, and rank targeted matches higher (`graph_match_score` + targeting). `backend/app/knowledge_graph/repository.py`.
- **Test:** `test_bug007_*`. Graph exclusion violations 13 → 0, crop-filter accuracy 0.35 → 1.0.

### BUG-008 / BUG-028 — Failures swallowed (MEDIUM)
- **Reproduction:** failure matrix F01–F06: 0/6. A DB, graph or Tavily outage produced no `retrieval_errors`.
- **Root cause:** every retriever (and `search_service`) caught all exceptions and returned `[]`. `retrieval_success` was defined as "returned ≥ 1 result", so an empty healthy channel looked like a failure and a failed channel looked like an empty one.
- **Fix:** retrievers raise, and the agent records the failing channel. The graph raises when unavailable. The DB retriever raises when a health check fails on an empty result. Success means "no error". The response status is `partial_results` only when a channel failed.
- **Test:** `test_bug008_*`.

### BUG-009 / BUG-010 / BUG-011 — Tavily and lookup issues
- 009: `search_web_schemes` returned only `{source, content}`. **Fix:** keep `title` and `url` (source URLs preserved, `.gov.in` trust works).
- 010: `"pm kusum" → "KUSUM"`, corpus ID is `PM_KUSUM` (merge case M03 produced two candidates). **Fix:** mapping corrected.
- 011: `search_by_name("")` matches everything. **Fix:** no profile + no query → no search.
- **Tests:** `test_bug009_*`, `test_bug010_*`, `test_bug011_*`.

### BUG-012 — Scheme cards empty of details (HIGH)
- **Reproduction:** E2E10: PM-KISAN card had no documents, steps or source URL.
- **Root cause:** (1) the DB retriever set `documents/application_steps/benefits = None`; (2) once Phase 5 eligibility existed, `_build_response_schemes` built cards **only** from eligibility results and discarded candidate details; (3) the frontend read `required_documents` / `source_url`, which the backend never sent.
- **Fix:** batch detail loader (5 queries for all candidates); cards merge candidate details with eligibility evidence and the XAI explanation; the frontend reads `documents` / `official_url`.
- **Test:** `test_bug012_*`, E2E10.

### BUG-013 — LLM reply not grounded (CRITICAL)
- **Reproduction:** a scripted LLM reply "Good news! You are eligible for … MKSP" (engine NOT_ELIGIBLE), or one with an invented URL, "Rs 10,000", or an invented scheme name, was returned to the user verbatim (A13–A16).
- **Root cause:** the formatter only checked reply length. The engine's structured status was correct, but the text contradicted it.
- **Fix:** `validate_llm_response()` rejects eligibility claims for non-ELIGIBLE schemes, global "eligible for all" claims, URLs and money amounts absent from the evidence, and bold scheme names that are not candidates. On rejection the deterministic, evidence-based reply is used. The prompt now marks retrieved text as untrusted. `backend/app/xai/response_validator.py`, `grounding.py`.
- **Test:** `test_bug013_*`.

### BUG-014 — Weak explanation validator (MEDIUM)
- **Reproduction:** XAI fabrication probes: 26/128 rejected (20.3%). "claim_eligible" was caught only for NOT_ELIGIBLE, never for NEEDS_MORE_INFORMATION or UNVERIFIABLE. Invented thresholds, URLs and criteria were never caught. The genuine explanation for an ELIGIBLE OR-rule scheme printed "Does not match:" and was itself rejected (X18).
- **Fix:** the validator checks sentence-level eligibility claims, numeric grounding, URL grounding and criterion grounding. The template lists OR-alternatives / optional rules under "Other options (not needed…)" instead of "Does not match".
- **Test:** `test_bug014_*`.

### BUG-015 — Rule source URL missing (MEDIUM)
- **Root cause:** `RuleResult.source_url` existed but nothing populated it. **Fix:** `evaluate_scheme(..., source_url=)` attaches the scheme's official corpus URL (never invented). The eligibility agent passes the candidate's `official_url`. Provenance check 0% → 100%.

### BUG-016 — Wrong follow-up question when the LLM is down (MEDIUM)
- **Root cause:** `generate_follow_up_question` returned the generic "Could you please tell me more about your farming land?" on failure, which overwrote the question agent's field-specific template, so it asked about land when the *state* was missing and repeated itself.
- **Fix:** it returns `None` on failure, and the deterministic template is kept. **Test:** `test_bug016_*`.

### BUG-017 — No profile canonicalisation / validation (MEDIUM)
- **Reproduction:** extracted `state="karnataka"` / `"KA"` stored verbatim. The DB state match is exact, so state schemes were missed. Values like `-5` acres, `NaN`, `inf`, `"Xyzland"` and SQL text were stored. A single invalid value (e.g. income `"abc"`) made pydantic reject the **whole** extraction.
- **Fix:** field validators on `FarmerProfile` canonicalise state (Indian states/UTs only), crop (corpus vocabulary), category and gender. They drop negative and non-finite numbers and implausible ages *per field*.
- **Test:** `test_bug017_*`.

### BUG-018 — Follow-up references (MEDIUM)
- **Root cause:** reference resolution relied entirely on the LLM, whose `referenced_scheme_id` was a guess at an ID it had never been shown. The fallback had no reference handling at all.
- **Fix:** a deterministic ordinal resolver over the previous answer's schemes runs first. Out-of-range ordinals produce a clarification question. LLM-provided IDs that were not in the previous answer are ignored. **Test:** `test_bug018_*`, PL20, PL21, E2E13.

### BUG-019 — Ranking determinism (MEDIUM)
- 6 distinct orders for 6 permutations of the same tied input. `result.scheme_id in graph_evidence` was always false because `graph_evidence` is a list of dicts. **Fix:** `scheme_id` tie-breaker; graph-evidence ID extraction. **Test:** `test_bug019_*`.

### BUG-020 — Hard-coded reviewer secret (HIGH)
- `REVIEW_API_KEY = "schemesetu-review-dev-2026"` in `api/review.py`. **Fix:** read from `REVIEW_API_KEY` env, compare in constant time, disable the API when unset. **Test:** `test_bug020_*`. Shared-secret auth is a documented limitation.

### BUG-021 / BUG-022 — Privacy (HIGH / MEDIUM)
- Logs contained `Profile updated: {... 'annual_income': 187654, 'category': 'SC', 'has_aadhaar': True}` and voice transcripts. Groq prompts (query rewriter, formatter) contained income/category/Aadhaar.
- **Fix:** log field names and lengths only. `llm_safe_profile_summary()` sends only state, district, land, crop and occupation. `redact_scheme_for_llm()` replaces sensitive user values in criteria with "(provided by user)". **Test:** `test_bug021_*`, `test_bug022_*`, adversarial A34/A35.

### BUG-023 / BUG-024 — Input limits (MEDIUM)
- 023: no `max_length` on chat messages. **Fix:** 2000 characters (configurable), blank messages rejected, limits on `thread_id` / `language` / TTS text.
- 024: MIME type trusted. **Fix:** magic-byte sniffing (WAV, WebM, Ogg, FLAC, MP4, MP3) must match the declared type before any ASR call.

### BUG-025 — Latency grew with every session (HIGH)
- **Reproduction:** offline per-request latency 144 → 244 → 350 → 452 ms over consecutive blocks of 40 requests; concurrent load P95 11.8 s.
- **Root cause:** LangGraph compares the checkpointer several times per request. `MemorySaver` is a pydantic-v1 model whose `__eq__` compares `.dict()`, i.e. **every stored conversation**. It also never evicted sessions.
- **How found:** cProfile → `pydantic.v1.main.__eq__` 7.6 s cumulative for 5 requests after 150 warm-up requests.
- **Fix:** `BoundedMemorySaver`: identity equality, O(1) repr, and LRU eviction beyond `MAX_SESSIONS` (default 1000). `backend/app/graph/workflow.py`.
- **After:** flat ≈ 98 ms per request over 200 consecutive requests. **Test:** `test_bug025_*`.

### BUG-026 / BUG-027 — Hygiene (LOW)
- 026: `f"DELETE FROM {table} …"` (table names from a constant list, values already parameterised) → `psycopg.sql.Identifier`.
- 027: `CRITICAL_FIELDS: list` was a pydantic field, so it appeared in every API profile and in the LLM's structured-output schema. → `ClassVar`.

### BUG-029 — Wrong golden label + missing categorical conflict detection (MEDIUM)
- `eligibility_cases.json` E26 expected **ELIGIBLE** for `state IN [karnataka] AND state IN [maharashtra]` with a Karnataka profile, which is impossible under the documented AND semantics (evaluator error). The engine answered NOT_ELIGIBLE, which is also misleading: the rule set is unsatisfiable, i.e. a data error, and §38 requires contradictory rules → UNVERIFIABLE.
- **Fix:** conflict detection extended to disjoint required EQ/IN rules on the same field. The dataset was bumped to `eligibility_v2` with `label_history` and a written justification (`evaluation/datasets/DATASET_VERSIONS.md`). This is **not** relabelling to match the system: the corrected label differs from both the old label and the old output.

### BUG-031 — Every UI message started a new session (HIGH)
- **Reproduction:** in the UI, type "Karnataka", then "2 acres", then "ragi" → three unrelated sessions, and the assistant keeps asking for the state.
- **Root cause:** `page.tsx` sent `thread_id: "default_session"`, and `chat.py` replaced that placeholder with a **new random UUID on every request**. API-level tests used explicit thread IDs, so the defect was invisible to them.
- **Fix:** one `crypto.randomUUID()` session per tab, and the backend echoes `thread_id`. **Test:** `test_bug031_*`.

### BUG-032 — UI dropped most response types (HIGH)
- `handleResponseData` handled only `asking_question`, `schemes_found` and `error`. A Tavily outage (`partial_results`), `no_results`, clarification questions and scheme details showed **nothing**. For `schemes_found` it replaced the real explanation and review notice with "I found N schemes". **Fix:** always show the reply; update schemes whenever present. **Test:** `test_bug032_*`.

### BUG-033 — Accessibility (LOW)
- `<html lang="en">` never followed the selected language. TTS audio could not be stopped and the `Audio` object was never released. The scheme-card expand button was 32 px. Focus styles were missing on most controls. A land size of 0 rendered as "Not set". **Fix:** `document.documentElement.lang` sync, a "Stop audio" button plus release on unmount and before recording, 44 px targets, `focus-visible` rings, and `!= null` checks. Covered by `evaluation/runners/accessibility_runner.py`.

### BUG-034 — Follow-up answer not focused (MEDIUM)
- **Found by:** `scripts/smoke_test.py --offline` (after the main fix pass): "documents for the first one" returned `['KCC', 'PKVY', …]`.
- **Root cause:** for a referenced scheme, the DB did an exact lookup but the graph still ran a profile-wide search. The merged list therefore contained other schemes, and it replaced `response_schemes`, so the *next* ordinal reference pointed into the wrong list.
- **Fix:** when `referenced_scheme_id` is resolved and present, retrieval keeps only that candidate. **Test:** `test_bug034_*`.

### BUG-035 — Health endpoints (LOW)
- `/health` computed graph status and discarded it. `/health/ready` never populated `graph_ready`. `/` reported version 0.1.0, `HealthResponse` 0.4.0, the app 0.6.0.
- **Fix:** single `APP_VERSION = "0.7.0-rc1"` in `core/config.py`; graph status reported. **Test:** `test_bug035_*`.

### Memory note (not a defect)
Measured by tracing: with the session cap at 50, the number of live `EligibilityResult` objects stayed at
1,250 (50 sessions × 25) across 100 further requests, so application state is bounded. Residual RSS growth
(~49 KB/request at the cap) comes from the intentionally uncapped in-memory review queue (one case per
session with unverifiable results) and allocator behaviour. A retained session holds about 300 KB, so the
default `MAX_SESSIONS=1000` can use about 300 MB. Lower it, or use a persistent checkpointer, for small
deployments (see limitations).
