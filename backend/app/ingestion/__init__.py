"""
Canonical Scheme Corpus Schema — Phase 1.

This is the single source of truth for government scheme data representation.
Every scheme in the corpus must conform to this schema.

Designed for:
- Phase 2: PostgreSQL import
- Phase 3: Knowledge Graph construction
- Phase 5: Deterministic eligibility engine
- Phase 6+: XAI, multilingual expansion
"""

from typing import List, Optional, Literal
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
from enum import Enum


# ============================================================
# Enumerations
# ============================================================

class SchemeLevel(str, Enum):
    CENTRAL = "central"
    STATE = "state"
    DISTRICT = "district"
    CENTRAL_STATE = "central_state"  # Joint central+state implementation
    UNKNOWN = "unknown"


class SchemeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"
    UNKNOWN = "UNKNOWN"


class SourceType(str, Enum):
    OFFICIAL_CENTRAL = "OFFICIAL_CENTRAL"
    OFFICIAL_STATE = "OFFICIAL_STATE"
    OFFICIAL_SCHEME_PORTAL = "OFFICIAL_SCHEME_PORTAL"
    SECONDARY = "SECONDARY"
    UNKNOWN = "UNKNOWN"


class RuleOperator(str, Enum):
    """Allowed operators for structured eligibility rules."""
    EQ = "EQ"
    NEQ = "NEQ"
    IN = "IN"
    NOT_IN = "NOT_IN"
    LT = "LT"
    LTE = "LTE"
    GT = "GT"
    GTE = "GTE"
    BETWEEN = "BETWEEN"
    CONTAINS = "CONTAINS"
    BOOLEAN = "BOOLEAN"
    UNKNOWN = "UNKNOWN"


class LogicalGroup(str, Enum):
    AND = "AND"
    OR = "OR"


class AadhaarRequirement(str, Enum):
    REQUIRED = "required"
    NOT_REQUIRED = "not_required"
    OPTIONAL = "optional"
    UNKNOWN = "unknown"


class BenefitType(str, Enum):
    FINANCIAL_ASSISTANCE = "financial_assistance"
    INSURANCE = "insurance"
    SUBSIDY = "subsidy"
    LOAN = "loan"
    INPUT_SUPPORT = "input_support"
    TRAINING = "training"
    INFRASTRUCTURE = "infrastructure"
    OTHER = "other"
    UNKNOWN = "unknown"


# ============================================================
# Sub-schemas
# ============================================================

class Benefit(BaseModel):
    """Structured benefit information."""
    type: BenefitType = BenefitType.UNKNOWN
    amount: Optional[str] = None
    currency: Optional[str] = "INR"
    frequency: Optional[str] = None
    condition: Optional[str] = None
    description: str
    source_text: Optional[str] = None


class EligibilityRule(BaseModel):
    """
    Structured eligibility rule.

    Only created when the source EXPLICITLY supports the conversion.
    Use operator=UNKNOWN when the source is ambiguous.
    """
    rule_id: Optional[str] = None
    field: str
    operator: RuleOperator
    value: object  # Can be str, int, float, list, bool
    logical_group: LogicalGroup = LogicalGroup.AND
    required: bool = True
    source_text: Optional[str] = None
    unit: Optional[str] = None
    original_value: Optional[object] = None
    original_unit: Optional[str] = None

    model_config = {"arbitrary_types_allowed": True}


class RequiredDocument(BaseModel):
    """Structured document requirement."""
    name: str
    mandatory: bool = True
    description: Optional[str] = None
    source_text: Optional[str] = None


class ApplicationStep(BaseModel):
    """Structured application step."""
    step_number: int
    description: str
    mode: Optional[str] = None  # online, offline, portal, CSC, etc.


class SourceRecord(BaseModel):
    """Source provenance record."""
    source_id: str
    url: Optional[str] = None
    source_type: SourceType = SourceType.UNKNOWN
    retrieved_at: Optional[str] = None
    last_verified_at: Optional[str] = None
    reference_text: Optional[str] = None
    content_hash: Optional[str] = None


# ============================================================
# Canonical Scheme Record
# ============================================================

class CanonicalScheme(BaseModel):
    """
    Canonical government scheme record.

    This is the authoritative representation for every scheme in the corpus.
    Fields marked Optional may be null/unknown — never fabricated.
    """

    # --- Identity ---
    scheme_id: str = Field(..., description="Stable machine-readable ID (e.g., PM_KISAN)")
    name: str = Field(..., description="Canonical full name")
    short_name: Optional[str] = Field(None, description="Common abbreviation")
    aliases: List[str] = Field(default_factory=list, description="Known name variants")

    # --- Description ---
    description: str = Field(..., description="Factual description from source")
    detailed_description: Optional[str] = None

    # --- Organization ---
    ministry: Optional[str] = None
    department: Optional[str] = None
    level: SchemeLevel = SchemeLevel.UNKNOWN
    scheme_type: Optional[str] = None  # e.g., "crop_insurance", "income_support"

    # --- Status ---
    status: SchemeStatus = SchemeStatus.UNKNOWN

    # --- Targeting ---
    target_beneficiaries: List[str] = Field(default_factory=list)
    applicable_states: Optional[List[str]] = None  # None = all states
    applicable_districts: Optional[List[str]] = None
    applicable_crops: Optional[List[str]] = None

    # --- Benefits ---
    benefits: List[Benefit] = Field(default_factory=list)

    # --- Eligibility ---
    eligibility_summary: Optional[str] = None
    eligibility_rules: List[EligibilityRule] = Field(default_factory=list)
    exclusions: List[str] = Field(default_factory=list)

    # --- Documents ---
    required_documents: List[RequiredDocument] = Field(default_factory=list)
    aadhaar_requirement: AadhaarRequirement = AadhaarRequirement.UNKNOWN

    # --- Application ---
    application_steps: List[ApplicationStep] = Field(default_factory=list)
    application_mode: List[str] = Field(default_factory=list)
    application_url: Optional[str] = None
    official_url: Optional[str] = None

    # --- Source Provenance ---
    source_records: List[SourceRecord] = Field(default_factory=list)

    # --- Versioning ---
    last_verified_at: Optional[str] = None
    data_version: str = "1.0"

    # --- Review ---
    possible_duplicate: bool = False
    needs_review: bool = False
    review_notes: Optional[str] = None

    model_config = {"extra": "ignore"}

    @field_validator("scheme_id")
    @classmethod
    def validate_scheme_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("scheme_id cannot be empty")
        return v.strip().upper()

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("name cannot be empty")
        return v.strip()


# ============================================================
# Source Registry Entry
# ============================================================

class SourceRegistryEntry(BaseModel):
    """Entry in the source registry — describes a data source."""
    source_id: str
    source_name: str
    organization: str
    source_type: SourceType
    base_url: Optional[str] = None
    official_status: str = "unknown"
    allowed_use: str = "public_information"
    retrieval_method: str = "manual"  # manual, scrape, api
    last_checked: Optional[str] = None
    notes: Optional[str] = None


# ============================================================
# Corpus Manifest
# ============================================================

class CorpusManifest(BaseModel):
    """Metadata about a corpus build."""
    corpus_version: str
    schema_version: str = "1.0.0"
    generated_at: str
    total_scheme_count: int = 0
    active_scheme_count: int = 0
    source_count: int = 0
    official_source_count: int = 0
    domains: List[str] = Field(default_factory=list)
    states: List[str] = Field(default_factory=list)
    validation_status: str = "pending"
    generator_version: str = "phase1-v1"
    content_hash: Optional[str] = None


# ============================================================
# Validation Report
# ============================================================

class ValidationIssue(BaseModel):
    """A single validation issue."""
    scheme_id: str
    issue_type: str  # ERROR or WARNING
    field: Optional[str] = None
    message: str
    current_value: Optional[object] = None
    recommended_action: Optional[str] = None

    model_config = {"arbitrary_types_allowed": True}


class ValidationReport(BaseModel):
    """Corpus validation report."""
    generated_at: str
    corpus_version: str
    total_schemes: int = 0
    valid_schemes: int = 0
    failed_schemes: int = 0
    warning_count: int = 0
    error_count: int = 0
    duplicate_count: int = 0
    official_source_percentage: float = 0.0
    missing_field_counts: dict = Field(default_factory=dict)
    rule_count: int = 0
    issues: List[ValidationIssue] = Field(default_factory=list)
    manual_review_count: int = 0


class ManualReviewItem(BaseModel):
    """Item flagged for manual review."""
    scheme_id: str
    issue_type: str
    field: Optional[str] = None
    current_value: Optional[object] = None
    source_url: Optional[str] = None
    explanation: str
    recommended_action: str

    model_config = {"arbitrary_types_allowed": True}
