# Phase 2 — Corpus to Database Mapping

## Mapping: Phase 1 Canonical Field → DB Table.Column

| Phase 1 Field | DB Table | DB Column | Notes |
|---|---|---|---|
| `scheme_id` | schemes | scheme_id | UNIQUE natural key |
| `name` | schemes | name | NOT NULL |
| `short_name` | schemes | short_name | |
| `aliases[]` | scheme_aliases | alias, normalized_alias | 1 row per alias |
| `description` | schemes | description | NOT NULL |
| `detailed_description` | schemes | detailed_description | |
| `ministry` | schemes | ministry | Kept in scheme row (no separate table) |
| `department` | schemes | department | |
| `level` | schemes | level | CHECK constraint |
| `scheme_type` | schemes | scheme_type | |
| `status` | schemes | status | CHECK constraint |
| `eligibility_summary` | schemes | eligibility_summary | Human-readable text |
| `eligibility_rules[]` | eligibility_rules | field_name, operator, value_json, etc. | 1 row per rule |
| `eligibility_rules[].field` | eligibility_rules | field_name | |
| `eligibility_rules[].operator` | eligibility_rules | operator | CHECK constraint |
| `eligibility_rules[].value` | eligibility_rules | value_json | JSONB (any type) |
| `eligibility_rules[].logical_group` | eligibility_rules | logical_group | AND or OR |
| `eligibility_rules[].source_text` | eligibility_rules | source_text | Preserved |
| `exclusions[]` | — | — | Not stored separately (kept in eligibility_summary) |
| `target_beneficiaries[]` | scheme_beneficiaries | beneficiary_type | 1 row per type |
| `applicable_states[]` | scheme_states | state | null = all states (no rows) |
| `applicable_districts[]` | scheme_districts | state, district | Only explicit districts |
| `applicable_crops[]` | scheme_crops | crop, normalized_crop | null = all crops (no rows) |
| `benefits[]` | scheme_benefits | benefit_type, amount, description, etc. | 1 row per benefit |
| `benefits[].type` | scheme_benefits | benefit_type | |
| `benefits[].amount` | scheme_benefits | amount | String (preserved as-is) |
| `benefits[].source_text` | scheme_benefits | source_text | Preserved |
| `required_documents[]` | scheme_documents | name, mandatory, description | 1 row per doc |
| `application_steps[]` | application_steps | step_number, description, mode | 1 row per step |
| `application_mode[]` | schemes | application_mode | JSONB array |
| `application_url` | schemes | application_url | |
| `official_url` | schemes | official_url | |
| `aadhaar_requirement` | schemes | aadhaar_requirement | |
| `source_records[]` | scheme_sources | source_id, url, source_type, etc. | 1 row per source |
| `source_records[].source_type` | scheme_sources | source_type | CHECK constraint |
| `source_records[].retrieved_at` | scheme_sources | retrieved_at | |
| `source_records[].content_hash` | scheme_sources | content_hash | |
| `data_version` | schemes | data_version | |
| `last_verified_at` | schemes | last_verified_at | DATE |
| `possible_duplicate` | schemes | possible_duplicate | BOOLEAN |
| `needs_review` | schemes | needs_review | BOOLEAN |

## Key Design Decisions

### null = "all" (no restriction)
For `applicable_states`, `applicable_crops`, and `applicable_districts`: when the Phase 1 field is `null`, **no rows** are inserted into the corresponding table. The search queries use `LEFT JOIN` + `NOT EXISTS` to include these schemes as "applicable to all."

### JSONB for flexible values
`eligibility_rules.value_json` uses PostgreSQL JSONB to store values of any type (string, number, boolean, array).

### First source is primary
During import, the first source in `source_records[]` is marked `is_primary = true`.

### Child record replacement on update
When a scheme is updated (same scheme_id, newer corpus), all child records are deleted and re-inserted. This is the "deterministic replacement" strategy — simple and correct.
