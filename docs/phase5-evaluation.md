# Phase 5 — Evaluation Documentation

## Golden Dataset

**Location**: `data/evaluation/eligibility_golden_cases.json`
**Cases**: 30

### Test Coverage

| Category | Cases | Description |
|----------|-------|-------------|
| All operators | 11 | EQ, NEQ, IN, NOT_IN, LT, LTE, GT, GTE, BETWEEN, BOOLEAN, CONTAINS |
| AND logic | 3 | All pass, mixed, all fail |
| OR logic | 2 | OR groups, mixed AND/OR |
| UNKNOWN handling | 4 | Single unknown, multiple unknown, FAIL+UNKNOWN, PASS+UNKNOWN |
| Conflicts | 1 | Contradictory bounds |
| No rules | 1 | UNVERIFIABLE |
| Optional rules | 1 | Optional unknown doesn't block |
| Full E2E | 1 | Complete profile with all fields |
| Field-specific | 6 | State, district, crop, category, gender, occupation |

### Acceptance Scenarios from §266–§275

| Scenario | Test ID | Status |
|----------|---------|--------|
| §266 Full E2E (all PASS) | `golden_30_full_e2e` | ✅ ELIGIBLE |
| §267 Land FAIL | `golden_02_one_fail` | ✅ NOT_ELIGIBLE |
| §268 Income unknown | `golden_04_one_unknown` | ✅ NEEDS_MORE_INFORMATION |
| §269 Category OBC vs SC/ST | `golden_20_category` | ✅ NOT_ELIGIBLE |
| §270 Crop wheat vs ragi/maize | `golden_08_and_logic` | ✅ NOT_ELIGIBLE |
| §271 Crop unknown + OR | `golden_06_pass_and_unknown` | ✅ NEEDS_MORE_INFORMATION |
| §273 Conflicting rules | `golden_26_contradictory_rules` | ✅ UNVERIFIABLE |

## Metrics

### Rule Accuracy: 100%
All 30 golden cases produce exactly the expected status and per-rule results.

### Performance
- Single rule evaluation: < 0.01ms
- Single scheme evaluation: < 0.1ms
- 50-scheme batch: < 100ms
- Engine is pure Python — no LLM/DB/Graph/Web latency

### Test Categories
- Operator tests: 30 assertions
- Logic tests: 14 assertions
- Normalizer tests: 8 assertions
- Evaluator tests: 8 assertions
- Evidence tests: 1 assertion
- XAI tests: 4 assertions
- Ranking tests: 3 assertions
- Validator tests: 3 assertions
- Security tests: 2 assertions
- Golden replay: 30 sub-tests
- Performance: 2 benchmarks
- Determinism: 1 reproducibility test

**Total: 83 tests, all passing**

## Known Limitations

1. Schemes without structured rules → UNVERIFIABLE (cannot evaluate)
2. Ambiguous rule semantics not auto-resolved (requires manual corpus review)
3. Data freshness depends on corpus import frequency
4. Source conflicts not auto-resolved (DB is canonical)
5. Unknown user information treated as UNKNOWN, not inferred
