# Phase 5 — Explainable AI (XAI) Documentation

## XAI Pipeline

```
EligibilityResult (from Engine)
        │
        ▼
Evidence Builder (evidence.py)
        │ ← categorizes: matched, failed, missing, conflicts
        ▼
Structured Explanation (explainer.py)
        │
        ▼
Template-based Natural Language (templates.py)
        │
        ▼
Validation (validate_explanation)
        │
        ▼
Final Explanation
```

## Evidence Building

Every rule result produces structured evidence:

```json
{
  "field": "land_size_acres",
  "operator": "LTE",
  "user_value": 2.0,
  "required_value": 5,
  "source_text": "Up to 5 acres",
  "explanation_key": "LAND_WITHIN_LIMIT"
}
```

## Explanation Templates (§193)

### ELIGIBLE
```
Summary: "Your profile matches the available eligibility criteria."
Matched:
  ✓ State: Karnataka
  ✓ Crop: Ragi
  ✓ Land size: 2 acres
```

### NEEDS_MORE_INFORMATION
```
Summary: "More information is needed to complete the assessment."
Missing:
  ○ Annual income (required: ₹2 lakh)
```

### NOT_ELIGIBLE
```
Summary: "One or more published criteria do not match the current profile."
Failed:
  ✗ Land size: Profile has 10, required: ≤ 5 (Up to 5 acres)
```

### UNVERIFIABLE
```
Summary: "The available structured criteria are insufficient to make a reliable assessment."
```

## Validation Rules

1. Explanation must not contradict engine status
2. No unsupported claims (no invented URLs, numbers)
3. No probability language ("90% chance")
4. No "guaranteed" language
5. Must use "available published criteria" phrasing

## LLM Integration

- The LLM is NEVER the source of eligibility decisions
- LLM may only simplify/explain evidence that already exists
- If LLM fails → deterministic template fallback
- If LLM output contradicts engine → rejected, fallback used
