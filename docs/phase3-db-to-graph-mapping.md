# Phase 3 — Database to Graph Mapping

## Table → Node Mapping

| PostgreSQL Table | Graph Element | Details |
|-----------------|---------------|---------|
| `schemes` | **SCHEME** nodes | scheme_id, name, status, level, ministry, department |
| `scheme_states` | **APPLIES_TO_STATE** edges | Scheme → State |
| `scheme_districts` | **APPLIES_TO_DISTRICT** edges | Scheme → District |
| `scheme_crops` | **TARGETS_CROP** edges | Scheme → Crop |
| `scheme_beneficiaries` | **TARGETS_BENEFICIARY** edges | Scheme → Beneficiary |
| `scheme_benefits` | **PROVIDES_BENEFIT** edges | Scheme → Benefit type node |
| `scheme_documents` | **REQUIRES_DOCUMENT** edges | Scheme → Document |
| `eligibility_rules` | **ELIGIBILITY_RULE** nodes + **HAS_ELIGIBILITY_RULE** edges | Rules also extract category/occupation/gender |
| `scheme_sources` | **SOURCE** nodes + **HAS_SOURCE** edges | Source provenance |
| `scheme_aliases` | Node attributes on SCHEME | Aliases stored as attributes, not separate nodes |
| `corpus_versions` | Graph metadata | corpus_version in graph.graph dict |

## Derived Nodes (not direct table mapping)

| Node Type | Derived From | Details |
|-----------|-------------|---------|
| MINISTRY | `schemes.ministry` column | Shared across multiple schemes |
| DEPARTMENT | `schemes.department` column | Shared across schemes |
| CATEGORY | `eligibility_rules` (field=category) | Extracted from rule values |
| OCCUPATION | `eligibility_rules` (field=occupation) | Extracted from rule values |
| GENDER | `eligibility_rules` (field=gender) | Extracted from rule values |
| COUNTRY | System-defined | COUNTRY:INDIA root node |
| STATE | `scheme_states` + rule extraction | Reused across schemes |
| CROP | `scheme_crops` | Reused across schemes |
| DOCUMENT | `scheme_documents` | Reused across schemes |
| BENEFIT | `scheme_benefits.type` | Categorized benefit types |

## Global Applicability
Schemes with **no** entries in `scheme_states` (null = all) are connected to `COUNTRY:INDIA` via `GLOBAL_APPLICABILITY` edge. They are NOT connected to every individual state.
