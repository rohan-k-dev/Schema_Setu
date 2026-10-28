# Phase 7 — Metric Definitions

All metrics are computed by `scripts/run_evaluation.py` from the runners in `evaluation/runners/`.
Helpers are in `evaluation/metrics/__init__.py`. Targets are **project-defined** unless a row cites Review-II.
A metric that cannot be computed is reported as `NOT_MEASURED`, never estimated.

| Metric | Definition | Formula | Dataset | Method | Interpretation |
|---|---|---|---|---|---|
| Scenario pass rate | Share of scenarios whose structured assertions all hold | passed / total | profile_logic, e2e, adversarial, review | runner checks; wording never compared (§132) | A scenario with any wrong field counts as failed (§12) |
| Precision | Share of returned items that are relevant | TP / (TP + FP) | — | set-based | High = little noise |
| Recall | Share of relevant items returned | TP / (TP + FN) | — | set-based | High = little missed |
| F1 | Harmonic mean of precision and recall | 2PR / (P + R) | profile_cases (live) | field level | Balances both |
| Precision@K | Share of the top-K merged candidates that are *applicable* to the profile | applicable in top K / K | retrieval_cases (K = 10) | applicability from hand-written targeting maps | 1.0 = no scheme for another state/crop in the top K |
| Targeted recall@K | Share of schemes specifically targeted at the user's state/crop that appear in the top K | targeted ∩ topK / targeted | retrieval_cases | — | The most specific schemes must not be cut |
| Exclusion violations | Count of schemes restricted to another state/crop returned at all | Σ |excluded ∩ returned| | retrieval_cases | graph & DB separately | Graph "false relationships" (§23) |
| State/crop filter accuracy | Share of cases with zero state- (crop-) exclusion violations | ok cases / cases | retrieval_cases | — | |
| Scheme-level accuracy | Share of cases where the final status equals the golden status | correct / cases | 4 eligibility datasets (104 cases) | `evaluate_scheme` | Target 1.0 (deterministic engine) |
| Rule-level accuracy | Share of golden rule results matching | correct / rules | phase5 golden (51 rules) | — | Identifies the exact failing rule (§30) |
| False-positive rate | ELIGIBLE when gold is NOT_ELIGIBLE | FP / gold NOT_ELIGIBLE | eligibility datasets | confusion matrix | **Critical** metric (§51) |
| False-negative rate | NOT_ELIGIBLE when gold is ELIGIBLE | FN / gold ELIGIBLE | eligibility datasets | confusion matrix | §52 |
| NEEDS_MORE_INFORMATION rate | Share of evaluations ending in NMI for *fully stated* reference profiles | NMI / evaluations | 5 reference profiles × 40 corpus schemes | causes split into missing user info / unsupported field / derivation gap (§53) | High values point to profile-model or rule gaps, not the user |
| UNVERIFIABLE rate | Share of evaluations ending UNVERIFIABLE | U / evaluations | same | — | Measures corpus rule coverage (22/40 schemes have no structured rules) (§54) |
| Rule provenance | Share of corpus rule results carrying source text, scheme ID, corpus version and (when the corpus has one) the official source URL | ok / rules | 25 corpus rules | — | §39 |
| XAI grounding (claims / numbers / URLs) | Share of explanations whose criteria, numbers and URLs all come from RuleResult evidence | ok / explanations | xai_cases (32) | regex extraction vs. evidence | §43–§45 |
| Fabrication rejection | Share of tampered explanations rejected by `validate_explanation` | rejected / probes | 128 probes from xai_cases | 4–5 probe types per case | §102 |
| Source citation | Share of cases with an official URL where the explanation cites it | cited / with URL | xai_cases | — | §45 |
| Language parity | Share of non-English cases whose profile / candidates / statuses / XAI evidence equal the English reference | equal / cases | multilingual_cases (21) | translation mocked offline | Pipeline invariance, **not** translation quality |
| Voice field accuracy | Share of expected profile fields correct after mocked ASR | correct / fields | voice_cases (18 fields) | — | Not ASR accuracy |
| WER | Word error rate = (S + D + I) / N | — | needs real audio | — | NOT_MEASURED (no ground-truth audio) |
| Latency mean / P50 / P95 | Mean and nearest-rank percentiles of request wall time | P95 = value at rank ⌈0.95·n⌉ | ≥ 20 requests | `time.perf_counter` around HTTP call | Offline = own processing only (external services mocked) |
| Error rate | Failed requests / requests | (HTTP ≠ 200 + status "error" + exceptions) / n | load test | — | |
| RSS growth at session cap | Process working-set growth over the last 100 of 300 requests once the session cap (100) is reached | RSS₃₀₀ − RSS₂₀₀ | performance runner | Windows `GetProcessMemoryInfo` | Bounded memory ⇒ small value |
| Task completion rate | Completed tasks / attempted tasks | — | user study records | — | NOT_MEASURED until real participants are recorded |
| Expert correct rate | Outputs rated CORRECT / rated outputs | — | expert ratings | — | NOT_MEASURED until an expert rates the sample |

## Status rules (scorecard)
`PASS` — target met. `PARTIAL` — within 80% of a `>=` target or 150% of a `<=` target. `FAIL` — otherwise.
`NOT_MEASURED` — no measurement exists. `INFO` — descriptive metric without a target.
