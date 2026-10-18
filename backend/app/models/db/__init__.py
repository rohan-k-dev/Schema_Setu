"""
Database domain models for SchemeSetu Phase 2.

These are typed Pydantic models that represent database rows.
Repositories return these — NOT raw tuples or dicts.
"""

from __future__ import annotations
from typing import Optional, List, Any
from datetime import datetime, date
from pydantic import BaseModel


# ─── Core Scheme ─────────────────────────────────────────────
class SchemeRow(BaseModel):
    """Single scheme record from the schemes table."""
    id: int
    scheme_id: str
    name: str
    short_name: Optional[str] = None
    description: str
    detailed_description: Optional[str] = None
    ministry: Optional[str] = None
    department: Optional[str] = None
    level: Optional[str] = None
    scheme_type: Optional[str] = None
    status: str = "ACTIVE"
    eligibility_summary: Optional[str] = None
    official_url: Optional[str] = None
    application_url: Optional[str] = None
    application_mode: Optional[List[str]] = None
    aadhaar_requirement: Optional[str] = None
    data_version: str = "1.0"
    last_verified_at: Optional[date] = None
    possible_duplicate: bool = False
    needs_review: bool = False
    review_notes: Optional[str] = None
    corpus_version_id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SchemeAliasRow(BaseModel):
    id: int
    scheme_id: int
    alias: str
    normalized_alias: str


class SchemeStateRow(BaseModel):
    id: int
    scheme_id: int
    state: str
    is_exclusive: bool = False


class SchemeDistrictRow(BaseModel):
    id: int
    scheme_id: int
    state: str
    district: str


class SchemeCropRow(BaseModel):
    id: int
    scheme_id: int
    crop: str
    normalized_crop: str


class SchemeBeneficiaryRow(BaseModel):
    id: int
    scheme_id: int
    beneficiary_type: str


class SchemeBenefitRow(BaseModel):
    id: int
    scheme_id: int
    benefit_type: str
    amount: Optional[str] = None
    currency: str = "INR"
    frequency: Optional[str] = None
    condition: Optional[str] = None
    description: str
    source_text: Optional[str] = None
    benefit_order: int = 0


# ─── Eligibility ─────────────────────────────────────────────
class EligibilityRuleRow(BaseModel):
    id: int
    scheme_id: int
    rule_id: Optional[str] = None
    field_name: str
    operator: str
    value_json: Any = None
    logical_group: str = "AND"
    required: bool = True
    source_text: Optional[str] = None
    unit: Optional[str] = None
    original_value: Any = None
    original_unit: Optional[str] = None
    rule_order: int = 0


# ─── Documents ───────────────────────────────────────────────
class SchemeDocumentRow(BaseModel):
    id: int
    scheme_id: int
    name: str
    mandatory: bool = True
    description: Optional[str] = None
    source_text: Optional[str] = None
    document_order: int = 0


# ─── Application Steps ──────────────────────────────────────
class ApplicationStepRow(BaseModel):
    id: int
    scheme_id: int
    step_number: int
    description: str
    mode: Optional[str] = None
    portal_name: Optional[str] = None
    portal_url: Optional[str] = None
    office_name: Optional[str] = None
    notes: Optional[str] = None


# ─── Sources ─────────────────────────────────────────────────
class SchemeSourceRow(BaseModel):
    id: int
    scheme_id: int
    source_id: str
    url: Optional[str] = None
    source_type: str
    source_name: Optional[str] = None
    retrieved_at: Optional[date] = None
    verified_at: Optional[date] = None
    content_hash: Optional[str] = None
    reference_text: Optional[str] = None
    is_primary: bool = False


# ─── Versioning ──────────────────────────────────────────────
class CorpusVersionRow(BaseModel):
    id: int
    version: str
    schema_version: str
    generated_at: Optional[datetime] = None
    imported_at: Optional[datetime] = None
    source_count: Optional[int] = None
    scheme_count: Optional[int] = None
    manifest_hash: Optional[str] = None
    notes: Optional[str] = None


class IngestionRunRow(BaseModel):
    id: int
    corpus_version_id: int
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: str = "RUNNING"
    records_read: int = 0
    records_inserted: int = 0
    records_updated: int = 0
    records_skipped: int = 0
    errors: int = 0
    warnings: int = 0
    error_message: Optional[str] = None
    source_snapshot: Optional[str] = None


# ─── Composite Detail Model ─────────────────────────────────
class SchemeDetail(BaseModel):
    """Full scheme with all child records — returned by get_with_details()."""
    scheme: SchemeRow
    aliases: List[str] = []
    states: List[str] = []
    districts: List[SchemeDistrictRow] = []
    crops: List[str] = []
    beneficiaries: List[str] = []
    benefits: List[SchemeBenefitRow] = []
    eligibility_rules: List[EligibilityRuleRow] = []
    documents: List[SchemeDocumentRow] = []
    application_steps: List[ApplicationStepRow] = []
    sources: List[SchemeSourceRow] = []
