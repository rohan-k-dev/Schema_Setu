# Phase 7 — Final Evaluation Report

SchemeSetu RC-1 (v0.7.0-rc1) · evaluation `phase7-eval-1.0.0` · runs `before` and `after`, offline,
2026-10-13. Every number below is taken from `data/evaluation/reports/{before,after}/results.json`.

## 1. Objective
Answer with evidence: *does the implemented SchemeSetu satisfy the Review-II requirements?* Method:
MEASURE → FIND PROBLEMS → FIX → RE-MEASURE → DOCUMENT (§4, §150).

## 2. System under test
FastAPI + LangGraph backend (profile, completeness, question, query-rewriter, retrieval, eligibility,
recommendation and formatter agents), PostgreSQL schema (corpus v1.0.0, 40 schemes), NetworkX Knowledge Graph
(179 nodes / 356 edges), deterministic eligibility engine v1.0.0, deterministic XAI, Sarvam language/voice
services, human-review queue, and the Next.js 15 frontend.

## 3. Environment
Windows 11, Python 3.11.4, Node 24.13.1, pytest 8.1.1, langgraph 0.0.31, langchain-core 0.1.53.
**No API keys and no running PostgreSQL** in this environment, so all runs are **offline**: Groq, Tavily and
Sarvam are mocked and the DB is a corpus-backed fixture that mirrors the repository SQL semantics
(`evaluation/fixtures/`). Manifest: `data/evaluation/evaluation_manifest.json`.

## 4. Datasets
Canonical location `evaluation/datasets/` (versions in `DATASET_VERSIONS.md`): profile 30 (live), profile-logic 22,
retrieval 43 (20 profiles + 10 lookups + 5 merge + 2 conflict + 6 failure), eligibility 104 (30 v2 + 30
Phase-5 golden + 36 corpus + 8 nested) + 10 truth-table rows + re-evaluation + conflict, XAI 32 (+128 probes),
multilingual 23, voice 28, adversarial 36, E2E 24. All labels were hand-written from the corpus rules or
documented semantics **before** the fixes. One label was corrected (E26, BUG-029), with written justification.

## 5. Functional evaluation (profile, completeness, questions, context)
Profile-layer scenarios: **8/22 → 22/22**. Fixed: field-specific questions with the LLM down (BUG-016);
canonical state/crop/category/gender and rejection of negative, NaN or unknown values (BUG-017); occupation and age
kept (BUG-004); ordinal follow-ups and clarification (BUG-018). LLM extraction accuracy (profile_cases.json):
**NOT_MEASURED** (needs `--live`).

## 6. Retrieval evaluation
| Metric | Before | After |
|---|---|---|
| Merged targeted recall@10 | 0.25 | **1.0** |
| Merged precision@10 | 1.0 | 1.0 |
| Graph false relationships | 13 | **0** |
| Graph crop-filter accuracy | 0.35 | **1.0** |
| Failure matrix (6 combos) | 0/6 | **6/6** |
| Merge correctness | 4/5 | 5/5 |
| Tavily pipeline checks | 1/3 | 3/3 (mocked) |
| Parallel retrieval (2 s + 1 s + 3 s) | 3.02 s | 3.01 s, concurrent |

## 7. Eligibility evaluation
Scheme-level accuracy **0.9615 → 1.0** (104 cases), rule-level 51/51, operator probes 34/34,
three-valued truth table 10/10, nested logic 8/8, determinism 40/40, rule provenance **0% → 100%**.
False-positive rate **2.86% → 0** (the false positive came from the OR-substring bug, BUG-002).
For five fully stated reference profiles × 40 schemes, NEEDS_MORE_INFORMATION fell from **29.5% → 2.5%**: 59 of 59
unknowns had come from profile fields the model could not hold. UNVERIFIABLE stays at **45%**, the share of the
corpus without structured rules (a corpus limitation).

## 8. XAI evaluation
Status consistency, claim, number and URL grounding: 100% after (status consistency was 93.75% before because
PM-KISAN results were wrong). Genuine explanations accepted: 31/32 → 32/32. Fabrication probes rejected:
**26/128 → 128/128**. Official source cited when available: **0% → 100%**. The deterministic fallback needs no LLM.

## 9. Multilingual evaluation
11 languages (en, hi, kn, ta, te, mr, bn, gu, od, pa, ml): profile, candidate, eligibility and XAI-evidence parity
21/21, translation presentation-only 21/21, numeric preservation 21/21, translation-failure fallback 2/2, both
before and after. **Caveat:** translation is mocked offline. This shows the pipeline is language-invariant, not
that Sarvam translates correctly (NOT_MEASURED).

## 10. Voice evaluation
Post-ASR pipeline 14/16 → **16/16**, voice field accuracy (given transcripts) 16/18 → 18/18, session continuity
1/2 → 2/2, failure fallbacks + upload security 9/10 → 10/10 (malformed audio now rejected before ASR).
**WER: NOT_MEASURED** (no ground-truth audio).

## 11. Human-review evaluation
21/22 → **22/22**: all four automatic triggers fire on real engine outputs (UNVERIFIABLE never did before);
INSUFFICIENT_DATA can be created manually; lifecycle, invalid transitions, all four reviewer actions, the audit
trail and the privacy strip all pass; the API returns 403 without or with a wrong key; no canonical data is mutated.
Escalation now runs inside the live pipeline (E2E20).

## 12. Security evaluation (red team)
36 probes: **17/36 → 36/36**. Covered: negative, NaN, infinite, unknown-state and SQL-text profile values;
numeric parsing attacks; prompt injection in web content; user override; LLM claiming eligibility, inventing a
URL, an amount or a scheme; no-candidate fabrication; static SQL / eval / XSS / secret scans; SQL text in the API;
graph injection; oversized, malformed and wrong-MIME audio; session isolation; reviewer auth; 100 000-character
messages; blank input; log and outbound-data privacy; duplicate submission.

## 13. Performance evaluation (offline: external services mocked)
| Measurement | Before | After |
|---|---|---|
| Text request mean / P95 | 348 / 393 ms | 108 / 114 ms |
| Voice round trip (mock ASR + TTS) P95 | 540 ms | 111 ms |
| Load: 200 requests, concurrency 10 — P95 / errors | 11.8 s / 0 | 1.26 s / 0 |
| Per-request cost over time | grows ≈ 2.5 ms per stored session | flat |

Stage breakdown (mean ms, after): profile 29 · completeness 6 · rewriter 18 · retrieval 16 · eligibility 11 ·
recommendation 4.5 · formatter 15.5. Per-language P50 ranges 96–100 ms across 11 languages (mocked translation).
Bottleneck (§119): before the fix, checkpointer equality comparisons (BUG-025). Live, the LLM, Tavily and Sarvam
calls will dominate. **Review-II 10–15 s target: NOT_MEASURED live**, so it is not claimed as achieved.

## 14. Stability evaluation
10-minute soak: **4,296 requests, 0 errors**, P95 146 ms. No graph reloads during the run. With the session cap
set to 100, memory grows +5.6 MB per 100 requests after the cap is reached (application objects are bounded, as
verified by object counting). The residual growth is the uncapped in-memory review queue. At the default cap of
1000 sessions a full store uses about 300 MB (RSS +413 MB over the soak). The 1–2 h target was not run (PARTIAL).

## 15. User study
Protocol, tasks, data model and analysis are implemented. **0 participants; all metrics NOT_MEASURED.**

## 16. Expert validation
A 13-output sample from real system outputs covers all §91 categories. **0 ratings; NOT_MEASURED.**

## 17. Defects found
35 (`docs/phase7-bug-register.md`): 4 CRITICAL, 10 HIGH, 13 MEDIUM, 8 LOW.

## 18. Fixes
All 35 fixed, each with a regression test (`backend/app/tests/test_phase7_regressions.py`, 92 tests). Backend
suite: 388 passed / 4 skipped (import broken) → **484 passed / 0 skipped**. Frontend `npm run build` clean.

## 19. Before / after
Scorecard: **19 PASS / 8 PARTIAL / 18 FAIL / 8 NOT_MEASURED → 47 PASS / 0 PARTIAL / 0 FAIL / 6 NOT_MEASURED**
(3 INFO rows in both). Full table: `docs/phase7-final-scorecard.md`, `data/evaluation/reports/before_after.json`.

## 20. Smoke test
`python scripts/smoke_test.py --offline`: 19/19 checks pass (health, languages, chat, eligibility, XAI,
documents/steps, session echo, follow-up, language switch, scheme API, oversized and malformed input, SQL text,
TTS, voice, review queue and resolution, review auth). A live run (`--base-url`) has not been done.

## 21. Limitations
`docs/phase7-limitations.md`.

## 22. Conclusion
Every requirement that can be measured offline now passes with evidence. The audit also showed that the
"Phase 6 complete" state was not true as delivered: the backend could not import, the UI lost context on every
message, and human review was disconnected. Those are fixed. What remains open is measurement that needs
external resources: live service accuracy and latency, real audio, real users, a domain expert, and a real
PostgreSQL run.

**Release-candidate decision (§204): READY_FOR_FINAL_DOCUMENTATION**, as RC-1 for the offline-verified scope, with
the NOT_MEASURED items listed as outstanding work before final submission. No CRITICAL or HIGH defects remain open.
