# Phase 7 — Non-Functional Requirements (§174)

| NFR | Target | Measured (offline, after fixes) | Status | Notes |
|---|---|---|---|---|
| Performance: response time | Review-II: ~10–15 s with parallel search | Own processing: text P95 102 ms, voice round trip P95 106 ms (external services mocked). Live: NOT_MEASURED | PARTIAL | Real latency is dominated by Groq/Tavily/Sarvam; `run_evaluation.py --live` measures it |
| Performance: parallel retrieval | Concurrent DB/Graph/Web | 3.01 s for 2 s + 1 s + 3 s mocked delays | PASS | |
| Performance: no degradation over time | Constant per-request cost | Before: 144 → 452 ms over 160 requests. After: flat ≈ 98 ms | PASS | BUG-025 |
| Reliability: error rate under load | 0% | 0 / 300 (100 sequential + 200 at concurrency 10); 0 errors in the 10-minute soak | PASS | |
| Reliability: graceful degradation | Each dependency can fail independently | failure matrix 6/6; LLM, ASR, TTS and translation fallbacks pass | PASS | |
| Stability: bounded memory | Plateau at the session cap | +4.9 MB per 100 requests at cap (review queue uncapped) | PASS (project target) | see limitations |
| Stability: long run | 1–2 h | 10-minute soak only | PARTIAL | |
| Scalability / modularity | Clear layers, replaceable services | repository / service / agent layers; mocks swap every external service | PASS (qualitative) | single-process session store |
| Multilingual support | Supported languages work equivalently | 11/11 parity offline | PARTIAL | live quality unmeasured |
| Accuracy: eligibility | Deterministic correctness | 104/104 cases, FP = FN = 0 | PASS | |
| Accuracy: retrieval | Targeted schemes never dropped | targeted recall@10 = 1.0, precision@10 = 1.0 | PASS | |
| Security | Red-team probes fail safely | 36/36 | PASS | shared-secret reviewer auth |
| Privacy | No sensitive values in logs or outbound prompts | A34/A35 pass; regression tests | PASS | |
| Accessibility | Labels, focus, 44 px, lang, live regions | 13/13 static checks | PASS (static) | no screen-reader session yet |
