# Phase 7 — Functional Requirements Matrix (§173)

Review-II does not number its requirements, so descriptive IDs are used here (§173: "do not invent requirement IDs").

| ID | Requirement | Component | Test evidence | Result |
|---|---|---|---|---|
| FR-PROFILE-EXTRACT | Extract profile fields from natural language without guessing | `agents/profile_agent.py`, `PROFILE_PROMPT_V1` | profile_cases.json (live only) | NOT_MEASURED offline |
| FR-PROFILE-CANON | Canonical, validated profile values | `models/profile.py` | PL12–PL19, A01–A07, test_bug017 | PASS |
| FR-PROFILE-CONFLICT | Detect changed values and ask for confirmation | `profile_agent._detect_conflicts`, question agent | PL02, PL03 | PASS |
| FR-COMPLETENESS | Ask for state → land → crop, one question at a time | completeness + question agents | PL04–PL07, PL11 | PASS |
| FR-CONTEXT | Keep the profile across turns, channels and languages | LangGraph checkpointer, per-tab session | PL10, VS1, VS2, E2E16, BUG-031 | PASS |
| FR-FOLLOWUP | Resolve "the second one"; ask when ambiguous | `query_rewriter.resolve_ordinal_reference` | PL20, PL21, E2E13, BUG-034 | PASS |
| FR-RETRIEVE-DB | State/crop-aware canonical search | `retrieval/db_retriever.py` | retrieval DB recall@10 = 1.0 | PASS |
| FR-RETRIEVE-KG | Profile → scheme candidates with evidence | graph repository | graph metrics | PASS |
| FR-RETRIEVE-WEB | Live search, URLs kept, official trust | `web_retriever.py`, `search_service.py` | Tavily pipeline 3/3 (mocked) | PASS (mocked) |
| FR-PARALLEL | DB + Graph + Web concurrently | `retrieval_agent.py` | 3.01 s vs 6 s | PASS |
| FR-MERGE | One candidate per scheme, all evidence kept | `merger.py` | merge 5/5 | PASS |
| FR-ELIGIBILITY | Deterministic four-status decision | `eligibility/evaluator.py` | 104 cases, 100% | PASS |
| FR-XAI | Evidence-only explanations; no fabricated claims | `xai/` | xai runner 100%, 128/128 probes | PASS |
| FR-RANK | Deterministic ranking by status then match | `recommendation/ranker.py` | 7/7 | PASS |
| FR-DOCS-STEPS | Documents, application steps and official source per scheme | formatter cards, DB batch loader | E2E10 | PASS |
| FR-MULTILINGUAL | Translate input/output only; same decision in any language | `language_service.py` | parity 100% (offline) | PASS offline |
| FR-VOICE | ASR → same pipeline → TTS, with fallbacks | `api/voice.py` | voice runner 28/28 | PASS (mocked) |
| FR-REVIEW | Escalate on deterministic triggers; reviewer actions; audit | review service/API | 22/22, E2E20 | PASS |
| FR-FALLBACK | Degrade per failing dependency, never claim eligibility without rules | retrieval agent, eligibility agent | failure matrix 6/6, E2E17–19 | PASS |
