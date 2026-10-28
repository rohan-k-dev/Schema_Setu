"""
Corpus schema module — re-exports canonical types.
"""
from app.ingestion import (
    CanonicalScheme,
    Benefit,
    EligibilityRule,
    RequiredDocument,
    ApplicationStep,
    SourceRecord,
    SourceRegistryEntry,
    CorpusManifest,
    ValidationReport,
    ValidationIssue,
    ManualReviewItem,
    SchemeLevel,
    SchemeStatus,
    SourceType,
    RuleOperator,
    LogicalGroup,
    AadhaarRequirement,
    BenefitType,
)

__all__ = [
    "CanonicalScheme", "Benefit", "EligibilityRule", "RequiredDocument",
    "ApplicationStep", "SourceRecord", "SourceRegistryEntry", "CorpusManifest",
    "ValidationReport", "ValidationIssue", "ManualReviewItem",
    "SchemeLevel", "SchemeStatus", "SourceType", "RuleOperator",
    "LogicalGroup", "AadhaarRequirement", "BenefitType",
]
