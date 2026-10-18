# Phase 1 — Corpus Schema Documentation

## Overview

The canonical scheme schema is defined in `backend/app/ingestion/__init__.py` using Pydantic models. Every scheme in the corpus must conform to this schema.

## Canonical Scheme Record

### Identity Fields

| Field | Type | Required | Description | Example |
|---|---|---|---|---|
| `scheme_id` | string | **Yes** | Stable machine-readable ID | `PM_KISAN` |
| `name` | string | **Yes** | Canonical full name | `Pradhan Mantri Kisan Samman Nidhi` |
| `short_name` | string | No | Common abbreviation | `PM-KISAN` |
| `aliases` | list[string] | No | Known name variants | `["PM Kisan", "PMKSN"]` |

### Description

| Field | Type | Required | Description |
|---|---|---|---|
| `description` | string | **Yes** | Factual description from source |
| `detailed_description` | string | No | Extended description |

### Organization

| Field | Type | Required | Allowed Values |
|---|---|---|---|
| `ministry` | string | No | Ministry name |
| `department` | string | No | Department name |
| `level` | SchemeLevel | No | `central`, `state`, `district`, `central_state`, `unknown` |
| `scheme_type` | string | No | e.g., `crop_insurance`, `income_support` |

### Status

| Field | Type | Required | Allowed Values |
|---|---|---|---|
| `status` | SchemeStatus | No | `ACTIVE`, `INACTIVE`, `SUSPENDED`, `UNKNOWN` |

### Targeting

| Field | Type | Description |
|---|---|---|
| `target_beneficiaries` | list[string] | e.g., `["farmers", "small farmers"]` |
| `applicable_states` | list[string] or null | `null` = all states (central) |
| `applicable_districts` | list[string] or null | `null` = all districts |
| `applicable_crops` | list[string] or null | `null` = all crops |

### Benefits

Each benefit is a structured object:

| Field | Type | Description |
|---|---|---|
| `type` | BenefitType | `financial_assistance`, `insurance`, `subsidy`, `loan`, `input_support`, `training`, `infrastructure`, `other`, `unknown` |
| `amount` | string or null | e.g., `"Rs. 6,000 per year"` |
| `currency` | string | Default: `"INR"` |
| `frequency` | string or null | e.g., `"3 installments per year"` |
| `condition` | string or null | Conditions for benefit |
| `description` | string | **Required**. Human-readable description |
| `source_text` | string or null | Original source text for traceability |

### Eligibility

| Field | Type | Description |
|---|---|---|
| `eligibility_summary` | string or null | Human-readable eligibility text |
| `eligibility_rules` | list[EligibilityRule] | Structured rules (see below) |
| `exclusions` | list[string] | Excluded categories |

### Eligibility Rule Schema

| Field | Type | Description |
|---|---|---|
| `rule_id` | string or null | Unique rule identifier |
| `field` | string | **Required**. Profile field: `state`, `land_size_acres`, `primary_crop`, `income`, `category`, `gender`, `age`, `occupation`, `has_land` |
| `operator` | RuleOperator | **Required**. See operators below |
| `value` | any | The comparison value |
| `logical_group` | LogicalGroup | `AND` (default) or `OR` |
| `required` | bool | Default: `true` |
| `source_text` | string or null | Original source text |
| `unit` | string or null | Unit of measurement |
| `original_value` | any | Original value before normalization |
| `original_unit` | string or null | Original unit before normalization |

### Allowed Rule Operators

| Operator | Meaning | Example |
|---|---|---|
| `EQ` | Equals | `field=state, value="Karnataka"` |
| `NEQ` | Not equals | `field=category, value="General"` |
| `IN` | In list | `field=state, value=["KA","TN"]` |
| `NOT_IN` | Not in list | `field=crop, value=["tobacco"]` |
| `LT` | Less than | `field=income, value=200000` |
| `LTE` | Less than or equal | `field=land_size_acres, value=5` |
| `GT` | Greater than | `field=age, value=18` |
| `GTE` | Greater than or equal | `field=land_size_acres, value=0.5` |
| `BETWEEN` | Range (inclusive) | `field=age, value=[18,40]` |
| `CONTAINS` | Contains substring | `field=crop_type, value="millet"` |
| `BOOLEAN` | Boolean check | `field=has_land, value=true` |
| `UNKNOWN` | Cannot be determined | Source is ambiguous |

**IMPORTANT**: Only use `UNKNOWN` when the source does NOT clearly support a structured rule. Never guess.

### Documents

| Field | Type | Description |
|---|---|---|
| `required_documents` | list[RequiredDocument] | Structured document list |
| `aadhaar_requirement` | AadhaarRequirement | `required`, `not_required`, `optional`, `unknown` |

Each RequiredDocument:

| Field | Type | Description |
|---|---|---|
| `name` | string | **Required**. Document name |
| `mandatory` | bool | Default: `true` |
| `description` | string or null | Additional details |
| `source_text` | string or null | Source evidence |

### Application

| Field | Type | Description |
|---|---|---|
| `application_steps` | list[ApplicationStep] | Ordered steps |
| `application_mode` | list[string] | e.g., `["online", "CSC", "bank"]` |
| `application_url` | string or null | Portal URL for applying |
| `official_url` | string or null | Scheme information page |

### Source Provenance

| Field | Type | Description |
|---|---|---|
| `source_records` | list[SourceRecord] | **At least 1 required** |

Each SourceRecord:

| Field | Type | Description |
|---|---|---|
| `source_id` | string | **Required**. References source_registry |
| `url` | string or null | Specific page URL |
| `source_type` | SourceType | `OFFICIAL_CENTRAL`, `OFFICIAL_STATE`, `OFFICIAL_SCHEME_PORTAL`, `SECONDARY`, `UNKNOWN` |
| `retrieved_at` | string or null | ISO date of retrieval |
| `last_verified_at` | string or null | ISO date of verification |
| `reference_text` | string or null | Relevant excerpt |
| `content_hash` | string or null | Hash for change detection |

### Versioning

| Field | Type | Description |
|---|---|---|
| `last_verified_at` | string or null | When scheme data was last verified |
| `data_version` | string | Schema version (default: `"1.0"`) |

### Review Flags

| Field | Type | Description |
|---|---|---|
| `possible_duplicate` | bool | Flagged by deduplicator |
| `needs_review` | bool | Flagged for manual review |
| `review_notes` | string or null | Reason for review flag |

## Future Database Mapping

| Schema | PostgreSQL Table |
|---|---|
| CanonicalScheme | `schemes` |
| EligibilityRule | `scheme_rules` |
| RequiredDocument | `scheme_documents` |
| ApplicationStep | `scheme_application_steps` |
| SourceRecord | `scheme_sources` |

## Future Knowledge Graph Entities

| Entity (Node) | Source |
|---|---|
| Scheme | CanonicalScheme |
| State | applicable_states |
| District | applicable_districts |
| Crop | applicable_crops |
| Category | eligibility_rules (category field) |
| Ministry | ministry |
| Benefit | benefits |
| Document | required_documents |
