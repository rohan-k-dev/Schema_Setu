# Phase 7 — Review-II Requirement Traceability (§172)

Evidence numbers are from `data/evaluation/reports/after/` (offline, 2026-10-13). Status vocabulary:
**PASS** = implemented and measured; **PARTIAL** = implemented, some aspect only measurable live / with people;
**NOT_MEASURED** = no evidence yet.

| Review-II objective | Implemented component(s) | Test / dataset | Metric (after) | Evidence | Status |
|---|---|---|---|---|---|
| 1. Agentic AI framework | LangGraph workflow `backend/app/graph/workflow.py` with profile, completeness, question, query-rewriter, retrieval, eligibility, recommendation and formatter agents | e2e_cases (24), profile_logic (22) | E2E 24/24; profile layer 22/22 | e2e + profile runner | PASS (offline); LLM steps not measured live |
| 2. Knowledge Graph integration | NetworkX graph (179 nodes / 356 edges), `knowledge_graph/repository.py`, `retrieval/graph_retriever.py` | retrieval_cases (20 profiles) | graph targeted recall@10 = 1.0, false relationships = 0 (13 before), crop-filter accuracy 1.0 (0.35 before) | retrieval runner | PASS |
| 3. Personalized eligibility analysis | Deterministic engine `eligibility/` (11 operators, Kleene logic, conflicts), profile model | 4 eligibility datasets (104 cases), 51 golden rules | scheme-level accuracy 1.0 (0.9615 before); FP rate 0 (0.0286 before); NMI rate for fully stated profiles 2.5% (29.5% before) | eligibility runner | PASS |
| 4. Explainable AI | Deterministic templates `xai/templates.py`, evidence builder, validators `xai/explainer.py`, `xai/response_validator.py` | xai_cases (32 + 128 probes), adversarial A13–A17 | grounding 100%; fabrication rejection 128/128 (26/128 before); source citation 100% (0% before) | xai + adversarial runners | PASS |
| 5. Multilingual and voice-based interaction | Language registry (11), `language_service.py`, `voice_service.py`, `/voice`, `/tts` | multilingual_cases (21 + 2), voice_cases (28) | language parity 100% (offline); post-ASR pipeline 16/16; failure fallbacks 10/10 | multilingual + voice runners | PARTIAL: Sarvam translation/ASR/TTS quality and WER not measured |
| 6. User-friendly interface | Next.js UI: language selector, voice state machine, scheme cards with documents/steps/source/XAI | accessibility audit (13 checks), smoke test | 13/13 static checks (9/13 before); UI session + status bugs fixed (BUG-031/032) | accessibility runner, smoke test | PARTIAL: user study not conducted |
| 7. Real-time assistance (10–15 s with parallel search) | `asyncio.gather` parallel retrieval with per-channel timeouts | parallel benchmark, performance runner | parallel 3.01 s vs 6 s sequential (mocked delays); offline processing P95 ≈ 0.1 s | performance runner | PARTIAL: live end-to-end latency NOT_MEASURED |
| 8. Human-in-the-loop support | `review_service.py` escalation + queue + audit, `/review-cases` API | review runner (22 checks), E2E20 | 22/22 (21/22 before); escalation now live in the pipeline (never before) | review runner | PASS (API only; in-memory queue) |

## SRS items
| SRS requirement | Evidence | Status |
|---|---|---|
| Text and voice input | E2E14, voice runner, smoke test | PASS (voice mocked) |
| Multiple Indian languages | 11 declared, 11 tested offline for parity | PARTIAL (live quality unmeasured) |
| Profile collection: state / district / land / crop / income / category / gender / Aadhaar | FarmerProfile + canonicalisation; profile_logic 22/22 | PASS (deterministic layer); LLM extraction live-only |
| Live + local scheme search | DB + Graph + Tavily; failure matrix 6/6 | PASS (Tavily mocked) |
| Eligibility filtering | eligibility runner | PASS |
| Personalized recommendations | recommendation runner 7/7 | PASS |
| Explanations | xai runner | PASS |
| Documents / application steps | E2E10; scheme cards (BUG-012) | PASS |
| Session context | PL10, PL22, VS1/VS2, BUG-031 | PASS |
| 10–15 s target with parallel search | parallel benchmark only | PARTIAL / NOT_MEASURED live |
| Fallback to cached/local data | failure matrix, E2E17–19 | PASS |
