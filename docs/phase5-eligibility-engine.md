# Phase 5 — Eligibility Engine Architecture

## Overview

The SchemeSetu Eligibility Engine is a **deterministic rule evaluation system** that evaluates structured eligibility rules against a farmer profile. It produces typed statuses with full evidence traceability.

> **Core Principle**: The LLM must NOT make the final eligibility decision. The deterministic engine is the source of truth.

## Architecture

```
Candidate Schemes (from Phase 4 retrieval)
        │
        ▼
Rule Repository (PostgreSQL)
        │
        ▼
Eligibility Engine (deterministic)
        │
    ┌───┼───┐
    ▼   ▼   ▼
  PASS FAIL UNKNOWN
    │   │    │
    └───┼────┘
        ▼
Logical Evaluator (three-valued AND/OR)
        │
        ▼
Final Status (ELIGIBLE/NOT_ELIGIBLE/NEEDS_MORE_INFORMATION/UNVERIFIABLE)
        │
        ▼
Evidence Builder
        │
        ▼
XAI Explainer (deterministic templates)
        │
        ▼
Recommendation Ranker
        │
        ▼
Response Formatter
```

## Service Dependency Graph

```
API
 ↓
Agentic Graph (LangGraph)
 ↓
Eligibility Agent → Recommendation Agent
 ↓
Eligibility Service
 ↓
Rule Repository
 ↓
PostgreSQL
```

## Inputs

| Input | Source | Type |
|-------|--------|------|
| `profile` | Profile Agent | `Dict[str, Any]` |
| `merged_candidates` | Retrieval Agent | `List[Dict]` |
| `rules` | Rule Repository | `List[EligibilityRuleRow]` |

## Outputs

| Output | Type | Description |
|--------|------|-------------|
| `eligibility_results` | `List[EligibilityResult]` | Per-scheme evaluation |
| `recommendation_results` | `List[RankedScheme]` | Ranked results |
| `missing_eligibility_fields` | `List[str]` | Fields needed for evaluation |

## Rule Statuses

| Status | Meaning |
|--------|---------|
| `PASS` | Profile satisfies the rule |
| `FAIL` | Profile does not satisfy the rule |
| `UNKNOWN` | Profile field is missing/unparseable |
| `NOT_APPLICABLE` | Rule value is null or rule is not relevant |

## Final Eligibility Statuses

| Status | When |
|--------|------|
| `ELIGIBLE` | All required rules PASS |
| `NOT_ELIGIBLE` | Any required rule FAILs (in AND group) |
| `NEEDS_MORE_INFORMATION` | No FAILs, but UNKNOWN rules exist |
| `UNVERIFIABLE` | No structured rules, conflicting rules, or config errors |

## Operators

| Operator | Use Case | Example |
|----------|----------|---------|
| `EQ` | Exact match | `state EQ "Karnataka"` |
| `NEQ` | Not equal | `category NEQ "General"` |
| `IN` | Member of set | `crop IN ["ragi", "maize"]` |
| `NOT_IN` | Excluded from set | `category NOT_IN ["General"]` |
| `LT` | Less than | `land < 5` |
| `LTE` | Less than or equal | `income <= 200000` |
| `GT` | Greater than | `land > 1` |
| `GTE` | Greater than or equal | `income >= 50000` |
| `BETWEEN` | Range check | `land BETWEEN [1, 5]` |
| `BOOLEAN` | Boolean match | `has_aadhaar BOOLEAN true` |
| `CONTAINS` | Substring match | `occupation CONTAINS "farm"` |

## UNKNOWN Semantics

- UNKNOWN never automatically becomes FAIL
- UNKNOWN in AND: if no FAIL → NEEDS_MORE_INFORMATION
- UNKNOWN in OR: if no PASS → remains UNKNOWN
- Missing profile field → UNKNOWN (not FAIL)

## Conflict Handling

- Contradictory rules (e.g., `land <= 5` AND `land >= 10`) → UNVERIFIABLE
- Source conflicts (DB vs web) → DB is canonical, conflict recorded

## Source Handling

- Every rule result retains `source_text` and `source_url`
- Corpus version tracked in EligibilityResult
- Engine version: `1.0.0`

## Security

- No `eval()` or `exec()` — typed operator dispatch only
- No SQL from LLM output — parameterized queries via repository
- No graph traversal from LLM output
- Profile evaluated locally — not sent to Groq for eligibility
