# Golden dataset versions

Canonical location for Phase 7 datasets: `evaluation/datasets/`. Phase 5/6 datasets that existing
tests depend on stay in `data/evaluation/` and are read from there (not duplicated).

Expected labels are human-curated. System output never overwrites a label. A label change needs a
written justification, a version bump and a `label_history` entry on the case.

| File | Version | Cases | Notes |
|---|---|---|---|
| profile_cases.json | profile_v1 | 30 | LLM extraction labels (live mode only) |
| profile_logic_cases.json | profile_logic_v1 | 22 | deterministic profile layer, multi-turn |
| retrieval_cases.json | retrieval_v1 | 20 profile + 10 lookup + 5 merge + 2 conflict + 6 failure | labels from corpus applicability fields |
| eligibility_cases.json | eligibility_v2 | 30 | v2: E26 relabelled ELIGIBLE → UNVERIFIABLE (BUG-029) |
| corpus_eligibility_cases.json | corpus_eligibility_v1 | 36 | real corpus rules |
| eligibility_logic_cases.json | eligibility_logic_v1 | 10 truth-table + 8 nested + 2 | Kleene logic |
| xai_cases.json | xai_v1 | 32 | + 128 generated fabrication probes |
| multilingual_cases.json | multilingual_v1 | 21 + 2 failure | 11 languages, mocked translation offline |
| voice_cases.json | voice_v1 | 16 + 2 sessions + 10 failure | mocked ASR offline |
| adversarial_cases.json | adversarial_v1 | 36 | red-team probes |
| e2e_cases.json | e2e_v1 | 24 | journeys through the real API |
| ../../data/evaluation/eligibility_golden_cases.json | phase5 | 30 | Phase 5 golden, rule-level labels |

## Change log
- 2026-10-13 `eligibility_cases.json` v1 → v2: case E26 ("Duplicate state rules") expected ELIGIBLE, which
  contradicts the documented AND semantics. The two required rules allow disjoint values, so the rule set is
  unsatisfiable. Under §38, contradictory rules → UNVERIFIABLE. The engine was extended to detect this
  (categorical conflict detection). Before the fix the engine returned NOT_ELIGIBLE, so neither the old label nor
  the old output was correct. Recorded as BUG-029.
