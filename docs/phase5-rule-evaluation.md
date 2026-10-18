# Phase 5 — Rule Evaluation Documentation

## Rule Evaluation Flow

```
EligibilityRuleRow + Profile
        │
        ▼
   Field Normalization (normalizer.py)
        │
        ▼
   Operator Dispatch (operators.py)
        │
        ▼
   RuleResult (PASS/FAIL/UNKNOWN/NOT_APPLICABLE)
```

## Examples

### Numeric: Land Size

```
Rule: land_size_acres LTE 5
Profile: { land_size_acres: 2 }
→ normalize: 2.0 <= 5.0
→ PASS
```

```
Rule: land_size_acres LTE 5
Profile: { land_size_acres: 10 }
→ normalize: 10.0 <= 5.0
→ FAIL
```

### Categorical: State

```
Rule: state IN ["Karnataka", "Tamil Nadu"]
Profile: { state: "KA" }
→ normalize: "karnataka" in ["karnataka", "tamil nadu"]
→ PASS
```

### Boolean: Aadhaar

```
Rule: has_aadhaar BOOLEAN true
Profile: { has_aadhaar: "yes" }
→ normalize: True == True
→ PASS
```

### AND Logic

```
Rules:
  R1: state IN ["Karnataka"]  → PASS
  R2: crop IN ["ragi"]        → PASS
  R3: land LTE 5              → FAIL

AND(PASS, PASS, FAIL) = FAIL → NOT_ELIGIBLE
```

### OR Logic

```
Rules:
  R1: category IN ["SC"]  (group: category_or) → FAIL
  R2: category IN ["ST"]  (group: category_or) → PASS

OR(FAIL, PASS) = PASS → contributes PASS to the AND group
```

### Nested AND/OR

```
Rules:
  R1: state IN ["Karnataka"]  (AND) → PASS
  R2: crop IN ["ragi"]        (AND) → PASS
  R3: category IN ["SC"]      (category_or) → FAIL
  R4: category IN ["ST"]      (category_or) → PASS

OR group result: OR(FAIL, PASS) = PASS
AND groups: AND(PASS, PASS, PASS) = PASS → ELIGIBLE
```

### UNKNOWN — Missing Field

```
Rule: annual_income LTE 200000
Profile: { } (no income provided)
→ user_value is None
→ UNKNOWN

AND(PASS, UNKNOWN) = UNKNOWN → NEEDS_MORE_INFORMATION
```

### Conflict Detection

```
Rules:
  R1: land_size_acres LTE 5
  R2: land_size_acres GTE 10

Upper bound: 5
Lower bound: 10
5 < 10 → CONTRADICTION → UNVERIFIABLE
```
