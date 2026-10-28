# Phase 7 — Expert Validation: Method and Report

**Status: SAMPLE PREPARED, NOT YET RATED — 0 expert ratings recorded.** All expert metrics are
`NOT_MEASURED` in `data/evaluation/expert_validation_report.json`. No claim of expert or government approval
is made.

## 1. Reviewers (§90)
Intended: one or two agriculture-domain faculty members, agricultural extension officers or practitioners
familiar with farmer-welfare schemes. Only the reviewer's *role* is recorded.

## 2. Sample (§91)
`evaluation/runners/expert_runner.py` regenerates `data/evaluation/expert_validation/sample_outputs.json` on every
evaluation run from **real system outputs** (offline pipeline, corpus v1.0.0). The current sample has 13
outputs covering:

| Category | Examples |
|---|---|
| simple eligibility | PM-KISAN, KCC for a Karnataka ragi farmer |
| multiple conditions | PM-KMY (land ≤ 5 and age 18–40) |
| state-specific | Andhra Pradesh and Maharashtra state schemes |
| crop-specific | NMOOP for a groundnut farmer |
| needs information | PM-KMY without age |
| not eligible | MKSP for a male farmer; PM-KISAN for a landless farmer |
| application information | Soil Health Card documents and steps |
| uncertain data | MGNREGA (residence unknown), AGMARKNET (no structured rules) |
| XAI explanation | MKSP / MOVCDNER for a woman farmer in Assam |

Each sample includes: query, profile summary, system status, matched / failed / missing criteria, the
deterministic explanation, documents, steps and the source URL.

## 3. Rating scheme (§92–§93)
Per sample: `expert_status`, `accuracy_rating` (CORRECT / PARTIALLY_CORRECT / INCORRECT), `xai_rating`
(XAI_CORRECT / XAI_INCORRECT), `source_rating` (SOURCE_CORRECT / SOURCE_INCORRECT) and comments.
Template: `data/evaluation/expert_validation/ratings.template.json`.

## 4. Disagreement policy (§94)
A disagreement **never** changes system output automatically. Each one is investigated and classified as
corpus problem / rule problem / source conflict / model problem / evaluator problem, then logged in the bug
register if it is a defect.

## 5. Results
| Metric | Value |
|---|---|
| Outputs rated | 0 |
| CORRECT / PARTIALLY_CORRECT / INCORRECT | NOT_MEASURED |
| XAI correctness | NOT_MEASURED |
| Source correctness | NOT_MEASURED |
| Disagreements | NOT_MEASURED |

## 6. Limitations
Expert review has not happened. Note also that the corpus encodes only the structured rules extracted in
Phase 1. An expert will likely flag scheme conditions that the corpus does not model (e.g. PM-KISAN exclusion
criteria for income-tax payers). Such findings are corpus-coverage issues, not engine errors.
