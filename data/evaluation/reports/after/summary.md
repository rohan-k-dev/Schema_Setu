# SchemeSetu evaluation — after

- Generated: 2026-10-13T18:21:40.497877+00:00
- Mode: offline
- App 0.7.0-rc1 · corpus 1.0.0 · graph 1.0.0 · engine 1.0.0
- Commit: a95ab12 (dirty working tree: True)

## Scorecard

| Category | Metric | Target | Actual | Status |
|---|---|---|---|---|
| Profile | Deterministic profile-layer scenarios pass rate | >= 1 | 1 | PASS |
| Profile | LLM extraction field F1 (live) | >= 0.9 | — | NOT_MEASURED |
| Retrieval | Merged targeted recall@10 | >= 0.9 | 1 | PASS |
| Retrieval | Merged precision@10 (applicable schemes) | >= 1 | 1 | PASS |
| Retrieval | DB targeted recall@10 | >= 0.9 | 1 | PASS |
| Retrieval | Graph false relationships (out-of-scope schemes) | <= 0 | 0 | PASS |
| Retrieval | Graph crop-filter accuracy | >= 1 | 1 | PASS |
| Retrieval | Exact lookup / adversarial query pass rate | >= 1 | 1 | PASS |
| Retrieval | Candidate merge correctness | >= 1 | 1 | PASS |
| Retrieval | Source-conflict handling | >= 1 | 1 | PASS |
| Retrieval | Failure matrix (6 combinations) | >= 1 | 1 | PASS |
| Retrieval | Tavily pipeline (URL kept, official linked, unrelated dropped) | >= 1 | 1 | PASS |
| Retrieval | Parallel retrieval (2s+1s+3s mocked) seconds | <= 4 | 3.002 | PASS |
| Eligibility | Scheme-level accuracy | >= 1 | 1 | PASS |
| Eligibility | Rule-level accuracy | >= 1 | 1 | PASS |
| Eligibility | False-positive rate (ELIGIBLE when gold NOT_ELIGIBLE) | <= 0 | 0 | PASS |
| Eligibility | False-negative rate | <= 0 | 0 | PASS |
| Eligibility | Operator coverage probes | >= 1 | 1 | PASS |
| Eligibility | Three-valued logic truth table | >= 1 | 1 | PASS |
| Eligibility | Rule provenance (source text + URL + version) | >= 1 | 1 | PASS |
| Eligibility | Determinism (same input -> same result) | >= 1 | 1 | PASS |
| Eligibility | UNKNOWNs caused by unsupported profile fields | info | 5 | INFO |
| Eligibility | NEEDS_MORE_INFORMATION rate (fully stated profiles) | info | 0.025 | INFO |
| Eligibility | UNVERIFIABLE rate (corpus rule coverage) | info | 0.45 | INFO |
| XAI | Status consistency | >= 1 | 1 | PASS |
| XAI | Supported-claim grounding | >= 1 | 1 | PASS |
| XAI | Numeric grounding | >= 1 | 1 | PASS |
| XAI | URL grounding | >= 1 | 1 | PASS |
| XAI | Genuine explanations accepted by validator | >= 1 | 1 | PASS |
| XAI | Fabrication probes rejected | >= 1 | 1 | PASS |
| XAI | Official source cited when available | >= 1 | 1 | PASS |
| Recommendation | Ranking checks | >= 1 | 1 | PASS |
| Multilingual | Profile parity across languages (offline) | >= 1 | 1 | PASS |
| Multilingual | Eligibility parity across languages (offline) | >= 1 | 1 | PASS |
| Multilingual | XAI evidence parity (offline) | >= 1 | 1 | PASS |
| Multilingual | Translation is presentation-only | >= 1 | 1 | PASS |
| Multilingual | Translation-failure fallback | >= 1 | 1 | PASS |
| Multilingual | Live Sarvam translation quality | >= — | — | NOT_MEASURED |
| Voice | Post-ASR pipeline (mocked ASR) | >= 1 | 1 | PASS |
| Voice | Voice/text session continuity | >= 1 | 1 | PASS |
| Voice | Failure fallbacks + upload security | >= 1 | 1 | PASS |
| Voice | Word error rate (real audio) | <= — | — | NOT_MEASURED |
| Human Review | HITL checks (escalation, lifecycle, audit, privacy, auth) | >= 1 | 1 | PASS |
| Security | Red-team probes passed | >= 1 | 1 | PASS |
| End-to-end | Golden journeys passed | >= 1 | 1 | PASS |
| Performance | Offline text request P95 (ms, external services mocked) | <= 2000 | 113.7 | PASS |
| Performance | Offline voice round trip P95 (ms, mocked ASR/TTS) | <= 3000 | 111.5 | PASS |
| Performance | Review-II live latency target 10-15 s | <= 15000 | — | NOT_MEASURED |
| Performance | Concurrent load error rate (200 req, c=10) | <= 0 | 0 | PASS |
| Performance | Concurrent load P95 (ms) | <= 5000 | 1257 | PASS |
| Stability | Graph reloads during run | <= 0 | 0 | PASS |
| Stability | RSS growth over last 100 requests at session cap (KB) | <= 10240 | 5572 | PASS |
| Stability | Soak test errors | <= 0 | 0 | PASS |
| Accessibility | Static accessibility audit checks | >= 1 | 1 | PASS |
| User Study | Task completion rate | >= — | — | NOT_MEASURED |
| Expert Validation | Outputs rated CORRECT | >= — | — | NOT_MEASURED |

Status counts: INFO=3, NOT_MEASURED=6, PASS=47

## Failing checks (first 15 per area)

