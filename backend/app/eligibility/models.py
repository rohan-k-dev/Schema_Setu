"""
Eligibility domain models — Phase 5.

Typed models for rule evaluation, eligibility decisions,
and evidence. These are the core data structures used by
the deterministic eligibility engine.

§10–§12, §44–§45, §55, §190
"""

from enum import Enum
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field

# Engine version — single source of truth (§170)
ELIGIBILITY_ENGINE_VERSION = "1.0.0"


# ─── Rule-level status (§11) ─────────────────────────────────

class RuleStatus(str, Enum):
    """Result of evaluating a single eligibility rule."""
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


# ─── Scheme-level eligibility status (§32) ───────────────────

class EligibilityStatus(str, Enum):
    """Final eligibility decision for a scheme."""
    ELIGIBLE = "ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    NEEDS_MORE_INFORMATION = "NEEDS_MORE_INFORMATION"
    UNVERIFIABLE = "UNVERIFIABLE"


# ─── Operator types (§12) ────────────────────────────────────

class RuleOperator(str, Enum):
    """Supported comparison operators for eligibility rules."""
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


# ─── Explanation item types (§190) ───────────────────────────

class ExplanationType(str, Enum):
    """Type of explanation item for XAI."""
    MATCHED = "MATCHED"
    FAILED = "FAILED"
    MISSING = "MISSING"
    CONFLICT = "CONFLICT"
    WARNING = "WARNING"


# ─── Rule evaluation result (§45) ────────────────────────────

class RuleResult(BaseModel):
    """Result of evaluating a single eligibility rule against a profile."""
    rule_id: Optional[str] = None
    field: str
    operator: str
    user_value: Any = None
    required_value: Any = None
    status: RuleStatus
    source_text: Optional[str] = None
    source_url: Optional[str] = None
    explanation_key: Optional[str] = None
    logical_group: str = "AND"
    required: bool = True
    unit: Optional[str] = None


# ─── Scheme eligibility result (§44) ─────────────────────────

class EligibilityResult(BaseModel):
    """Complete eligibility evaluation for one scheme."""
    scheme_id: str
    scheme_name: str = ""
    status: EligibilityStatus
    rule_results: List[RuleResult] = Field(default_factory=list)
    passed_rules: int = 0
    failed_rules: int = 0
    unknown_rules: int = 0
    not_applicable_rules: int = 0
    missing_information: List[str] = Field(default_factory=list)
    conflicts: List[Dict[str, Any]] = Field(default_factory=list)
    source_references: List[Dict[str, str]] = Field(default_factory=list)
    evidence_summary: Optional[str] = None
    corpus_version: str = "1.0.0"
    engine_version: str = ELIGIBILITY_ENGINE_VERSION
    needs_review: bool = False

    def to_response_dict(self) -> Dict[str, Any]:
        """Serialize for API response (§92, §160)."""
        matched = [
            {"field": r.field, "user_value": r.user_value, "required_value": r.required_value}
            for r in self.rule_results if r.status == RuleStatus.PASS
        ]
        failed = [
            {"field": r.field, "user_value": r.user_value, "required_value": r.required_value,
             "source_text": r.source_text}
            for r in self.rule_results if r.status == RuleStatus.FAIL
        ]
        missing = [
            {"field": r.field, "required_value": r.required_value}
            for r in self.rule_results if r.status == RuleStatus.UNKNOWN
        ]

        return {
            "scheme_id": self.scheme_id,
            "eligibility_status": self.status.value,
            "matched_criteria": matched,
            "failed_criteria": failed,
            "missing_information": self.missing_information,
            "missing_criteria": missing,
            "passed_rules": self.passed_rules,
            "failed_rules": self.failed_rules,
            "unknown_rules": self.unknown_rules,
            "source_references": self.source_references,
            "evidence_summary": self.evidence_summary,
            "corpus_version": self.corpus_version,
            "engine_version": self.engine_version,
        }


# ─── Explanation item (§190) ─────────────────────────────────

class ExplanationItem(BaseModel):
    """Single item in an XAI explanation."""
    type: ExplanationType
    field: str
    status: RuleStatus
    user_value: Any = None
    required_value: Any = None
    text_key: Optional[str] = None
    source: Optional[str] = None


# ─── Full explanation (§48, §55) ──────────────────────────────

class EligibilityExplanation(BaseModel):
    """Full structured explanation for a scheme's eligibility."""
    summary: str
    matched_criteria: List[ExplanationItem] = Field(default_factory=list)
    failed_criteria: List[ExplanationItem] = Field(default_factory=list)
    missing_criteria: List[ExplanationItem] = Field(default_factory=list)
    cautions: List[str] = Field(default_factory=list)
    sources: List[Dict[str, str]] = Field(default_factory=list)
