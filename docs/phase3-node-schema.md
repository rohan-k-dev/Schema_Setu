# Phase 3 — Node Schema

## Node Types (14 + 1 root)

| Node Type | ID Format | Key Attributes | Example |
|-----------|-----------|----------------|---------|
| SCHEME | `SCHEME:<scheme_id>` | name, status, level, ministry, department | `SCHEME:PM_KISAN` |
| STATE | `STATE:<NAME>` | canonical_name, normalized_name | `STATE:KARNATAKA` |
| DISTRICT | `DISTRICT:<STATE>:<NAME>` | name, state | `DISTRICT:KARNATAKA:MANDYA` |
| CROP | `CROP:<NAME>` | canonical_name, normalized_name | `CROP:RAGI` |
| BENEFICIARY | `BENEFICIARY:<TYPE>` | canonical_name | `BENEFICIARY:FARMER` |
| CATEGORY | `CATEGORY:<CODE>` | canonical_name | `CATEGORY:SC` |
| OCCUPATION | `OCCUPATION:<TYPE>` | canonical_name | `OCCUPATION:FARMER` |
| GENDER | `GENDER:<VALUE>` | canonical_name | `GENDER:FEMALE` |
| MINISTRY | `MINISTRY:<NAME>` | canonical_name | `MINISTRY:MINISTRY_OF_AGRICULTURE_AND_FARMERS_WELFARE` |
| DEPARTMENT | `DEPARTMENT:<NAME>` | canonical_name | `DEPARTMENT:DEPARTMENT_OF_AGRICULTURE` |
| BENEFIT | `BENEFIT:<TYPE>` | canonical_name | `BENEFIT:FINANCIAL_ASSISTANCE` |
| DOCUMENT | `DOCUMENT:<NAME>` | canonical_name, normalized_name | `DOCUMENT:AADHAAR_CARD` |
| ELIGIBILITY_RULE | `ELIGIBILITY_RULE:<ID>` | field_name, operator, value, required, logical_group, source_text | `ELIGIBILITY_RULE:PM_KISAN_0` |
| SOURCE | `SOURCE:<ID>` | source_type, source_name, url, verified_at | `SOURCE:PMKISAN_GOV` |
| COUNTRY | `COUNTRY:INDIA` | canonical_name | `COUNTRY:INDIA` |

## Normalization Rules
All node ID components are:
- Uppercased
- Trimmed
- Spaces → underscores
- Special characters removed (parentheses, commas, quotes)
- `&` → `AND`

## Skipped Values
Values like `unknown`, `none`, `null`, `n/a`, empty strings do NOT create nodes.
