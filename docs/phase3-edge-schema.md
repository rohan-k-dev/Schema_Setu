# Phase 3 — Edge Schema

## Edge Types (17 total)

| Edge Type | Source Node | Target Node | Direction | Attributes |
|-----------|------------|-------------|-----------|------------|
| APPLIES_TO_STATE | SCHEME | STATE | Scheme → State | corpus_version |
| APPLIES_TO_DISTRICT | SCHEME | DISTRICT | Scheme → District | corpus_version |
| TARGETS_CROP | SCHEME | CROP | Scheme → Crop | corpus_version |
| TARGETS_BENEFICIARY | SCHEME | BENEFICIARY | Scheme → Beneficiary | corpus_version |
| TARGETS_CATEGORY | SCHEME | CATEGORY | Scheme → Category | corpus_version |
| TARGETS_OCCUPATION | SCHEME | OCCUPATION | Scheme → Occupation | corpus_version |
| TARGETS_GENDER | SCHEME | GENDER | Scheme → Gender | corpus_version |
| OFFERED_BY_MINISTRY | SCHEME | MINISTRY | Scheme → Ministry | corpus_version |
| BELONGS_TO_DEPARTMENT | SCHEME | DEPARTMENT | Scheme → Department | corpus_version |
| PROVIDES_BENEFIT | SCHEME | BENEFIT | Scheme → Benefit | corpus_version, source_text |
| REQUIRES_DOCUMENT | SCHEME | DOCUMENT | Scheme → Document | mandatory, corpus_version |
| HAS_ELIGIBILITY_RULE | SCHEME | ELIGIBILITY_RULE | Scheme → Rule | corpus_version |
| HAS_SOURCE | SCHEME | SOURCE | Scheme → Source | corpus_version |
| GLOBAL_APPLICABILITY | SCHEME | COUNTRY | Scheme → Country | corpus_version |
| LOCATED_IN_STATE | STATE | COUNTRY | State → Country | — |
| DISTRICT_OF | DISTRICT | STATE | District → State | — |
| PART_OF | STATE | COUNTRY | State → Country | — |

## Edge Direction Convention
All primary relationships flow **FROM** the scheme **TO** the related entity.
Geographic hierarchy flows upward: District → State → Country.

## Edge Attributes
Common edge attributes:
- `relation`: The EdgeType enum value
- `corpus_version`: Which corpus version created this edge
- `source_text`: Original text reference (for benefits, rules)
- `mandatory`: Whether a document is mandatory (for REQUIRES_DOCUMENT)
