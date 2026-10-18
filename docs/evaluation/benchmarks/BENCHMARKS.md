# Performance & Deployment Benchmark Report

All numbers are **measured**. Sources: `data/evaluation/reports/after/results.json` (Phase 7, 2026-10-13, offline;
fixture DB) and `data/evaluation/reports/benchmarks/component_latency.json` (Phase 8, 2026-10-14, **real
PostgreSQL 16**). Machine: Windows 11, Python 3.11.4, local Docker. External services (Groq, Tavily, Sarvam)
were **mocked** in every run below, so these are SchemeSetu's own processing times, **not** user-facing
latency.

## Review-II performance goal
| Target | Measured | Status | Notes |
|---|---|---|---|
| Results in about 10–15 s using parallel search | Own processing: P50 115 ms / P95 152 ms per full pipeline run (real DB, LLM mocked). Live end-to-end with Groq/Tavily/Sarvam: **not measured** | **NOT MEASURED** (live) | Parallelism is verified: 2 s + 1 s + 3 s mocked channel delays complete in 3.01 s (sequential would be 6 s). Live latency will be dominated by up to 3 Groq calls, Tavily (≤10 s timeout) and, for voice, Sarvam. Measure with `python scripts/run_evaluation.py --live` |

## Component latency (Phase 8, real PostgreSQL, n = 30 each)
| Component | Mean | P50 | P95 |
|---|---|---|---|
| Database retrieval (SQL search + batched details for ≤40 schemes) | 13.0 ms | 10.3 ms | 13.1 ms |
| Knowledge Graph traversal | 0.7 ms | 0.7 ms | 0.8 ms |
| Web retrieval (Tavily mocked → overhead only) | 0.2 ms | 0.2 ms | 0.3 ms |
| Candidate merge | 0.5 ms | 0.5 ms | 0.6 ms |
| Eligibility (batched rule load from PostgreSQL + evaluation of 25 candidates) | 2.5 ms | 2.4 ms | 2.9 ms |
| Full LangGraph pipeline (LLM mocked) | 121.5 ms | 114.7 ms | 152.4 ms |

## API-level (Phase 7 `after` run, fixture DB, all external services mocked)
| Measurement | n | Mean | P50 | P95 |
|---|---|---|---|---|
| Text request `/chat` | 25 | 108 ms | 105 ms | 114 ms |
| Voice round trip `/voice` + `/tts` (mock ASR/TTS) | 20 | 109 ms | 109 ms | 111 ms |
| Load: sequential | 100 | 101 ms | 98 ms | 111 ms |
| Load: concurrency 10 | 200 | 1,116 ms | 1,098 ms | 1,257 ms (0 errors) |
| Soak 10 min | 4,296 | 139 ms | 127 ms | 146 ms (0 errors) |

Per-node mean (ms): profile 29 · completeness 6 · query rewriter 18 · retrieval 16 · eligibility 11 ·
recommendation 4.5 · formatter 15.5. Per-language P50 across 11 languages: 96–100 ms (translation mocked).

Concurrency note: requests are effectively serialised inside one process (CPU-bound graph work on the event
loop), so latency at concurrency 10 ≈ 10 × single latency. Scale-out options are in `DEPLOYMENT.md`.

## Not measured (and why)
| Metric | Why |
|---|---|
| LLM latency (Groq) | No API key in the evaluation environment |
| Web-search latency (Tavily) | No API key |
| Voice processing / TTS latency (Sarvam) | No API key; no real audio corpus |
| Total live E2E latency vs 10–15 s | Requires the three services above |

## Deployment benchmarks (Phase 8)
| Step | Measured |
|---|---|
| `docker compose build` (3 images, cold cache) | 93 s |
| `docker compose up -d` → backend and frontend responding | 25 s |
| Clean `python:3.11-slim` container: `pip install -r requirements.txt` | 26 s |
| … `pytest` (495 tests at that point) | 8 s |
| … offline evaluation (no performance runner) | 17 s |
| Total clean-container reproduction | 55 s |

## Before/after (Phase 7 fix BUG-025)
Concurrent load P95 11.8 s → 1.26 s; per-request latency no longer grows with the number of stored sessions.
