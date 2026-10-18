# Phase 5 — Recommendation Ranking Documentation

## Ranking Principle

> Ranking ≠ eligibility probability.

The ranking is a **deterministic, transparent ordering** based on eligibility status and profile match strength. No ML model, no reinforcement learning, no probability scores.

## Ranking Precedence (§59)

| Priority | Status | Label |
|----------|--------|-------|
| 1 (highest) | `ELIGIBLE` | Matches available criteria |
| 2 | `NEEDS_MORE_INFORMATION` | More information needed |
| 3 | `NOT_ELIGIBLE` | Does not match current criteria |
| 4 (lowest) | `UNVERIFIABLE` | Could not verify |

## Within-Status Ranking

Within the same status, schemes are ranked by **profile match score**:

```
profile_match_score = passed_rules / (passed_rules + failed_rules + unknown_rules)
```

This is NOT a probability. It is a transparent ranking signal.

## Tie-Breaking

1. More matched criteria → ranked higher
2. Official source available → slight boost
3. Knowledge graph match → minor boost (+0.01)

## Example

```
Scheme A: ELIGIBLE, score=1.0 (3/3 pass)    → Rank 1
Scheme B: ELIGIBLE, score=0.75 (3/4 pass)   → Rank 2
Scheme C: NEEDS_MORE_INFORMATION, score=0.5  → Rank 3
Scheme D: NOT_ELIGIBLE, score=0.25           → Rank 4
Scheme E: UNVERIFIABLE                       → Rank 5
```

## What We Do NOT Do

- ❌ No "best scheme for you" language
- ❌ No eligibility probability (e.g., "90% chance")
- ❌ No ML-based recommendation model
- ❌ No reinforcement learning
- ❌ No "guaranteed" claims

## What We Do

- ✓ "Matches your profile based on available published criteria"
- ✓ "Most closely matched based on verified criteria"
- ✓ Transparent, explainable ranking
- ✓ Deterministic — same input always produces same output
