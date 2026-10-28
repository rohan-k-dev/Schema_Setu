"""
Validator — checks corpus data quality.

Produces structured validation reports with hard errors and soft warnings.
"""

from typing import List, Set
from datetime import datetime

from app.ingestion import (
    CanonicalScheme, ValidationReport, ValidationIssue,
    ManualReviewItem, RuleOperator, SchemeStatus,
)
from app.ingestion.normalizer import validate_url_format
from app.core.logging import get_logger

logger = get_logger(__name__)


def validate_corpus(schemes: List[CanonicalScheme], corpus_version: str = "1.0.0") -> ValidationReport:
    """
    Validate a list of canonical schemes.

    Returns a ValidationReport with errors, warnings, and statistics.
    """
    report = ValidationReport(
        generated_at=datetime.utcnow().isoformat(),
        corpus_version=corpus_version,
        total_schemes=len(schemes),
    )

    seen_ids: Set[str] = set()
    valid_count = 0
    issues: List[ValidationIssue] = []

    for scheme in schemes:
        scheme_valid = True
        scheme_issues = _validate_scheme(scheme, seen_ids)

        for issue in scheme_issues:
            issues.append(issue)
            if issue.issue_type == "ERROR":
                report.error_count += 1
                scheme_valid = False
            else:
                report.warning_count += 1

        if scheme_valid:
            valid_count += 1

        seen_ids.add(scheme.scheme_id)

        # Count rules
        report.rule_count += len(scheme.eligibility_rules)

    report.valid_schemes = valid_count
    report.failed_schemes = len(schemes) - valid_count
    report.issues = issues

    # Calculate official source percentage
    total_sources = 0
    official_sources = 0
    for scheme in schemes:
        for src in scheme.source_records:
            total_sources += 1
            if src.source_type.value.startswith("OFFICIAL"):
                official_sources += 1
    if total_sources > 0:
        report.official_source_percentage = round(official_sources / total_sources * 100, 1)

    # Count missing fields
    missing_counts = {}
    for scheme in schemes:
        if not scheme.eligibility_summary:
            missing_counts["eligibility_summary"] = missing_counts.get("eligibility_summary", 0) + 1
        if not scheme.benefits:
            missing_counts["benefits"] = missing_counts.get("benefits", 0) + 1
        if not scheme.required_documents:
            missing_counts["required_documents"] = missing_counts.get("required_documents", 0) + 1
        if not scheme.application_steps:
            missing_counts["application_steps"] = missing_counts.get("application_steps", 0) + 1
        if not scheme.application_url:
            missing_counts["application_url"] = missing_counts.get("application_url", 0) + 1
        if not scheme.official_url:
            missing_counts["official_url"] = missing_counts.get("official_url", 0) + 1
    report.missing_field_counts = missing_counts

    # Count duplicates
    report.duplicate_count = sum(1 for s in schemes if s.possible_duplicate)
    report.manual_review_count = sum(1 for s in schemes if s.needs_review)

    logger.info(
        f"Validation complete: {valid_count}/{len(schemes)} valid, "
        f"{report.error_count} errors, {report.warning_count} warnings"
    )

    return report


def _validate_scheme(scheme: CanonicalScheme, seen_ids: Set[str]) -> List[ValidationIssue]:
    """Validate a single scheme. Returns list of issues."""
    issues = []

    # === HARD ERRORS ===

    # E1: Empty scheme_id
    if not scheme.scheme_id or not scheme.scheme_id.strip():
        issues.append(ValidationIssue(
            scheme_id=scheme.scheme_id or "UNKNOWN",
            issue_type="ERROR",
            field="scheme_id",
            message="Missing scheme_id",
            recommended_action="Add a stable scheme ID",
        ))

    # E2: Duplicate scheme_id
    if scheme.scheme_id in seen_ids:
        issues.append(ValidationIssue(
            scheme_id=scheme.scheme_id,
            issue_type="ERROR",
            field="scheme_id",
            message=f"Duplicate scheme_id: {scheme.scheme_id}",
            recommended_action="Merge or rename duplicate",
        ))

    # E3: Empty name
    if not scheme.name or not scheme.name.strip():
        issues.append(ValidationIssue(
            scheme_id=scheme.scheme_id,
            issue_type="ERROR",
            field="name",
            message="Missing scheme name",
            recommended_action="Add canonical name from source",
        ))

    # E4: No source records
    if not scheme.source_records:
        issues.append(ValidationIssue(
            scheme_id=scheme.scheme_id,
            issue_type="ERROR",
            field="source_records",
            message="No source records — scheme has no provenance",
            recommended_action="Add at least one source record",
        ))

    # E5: Invalid status
    try:
        SchemeStatus(scheme.status)
    except ValueError:
        issues.append(ValidationIssue(
            scheme_id=scheme.scheme_id,
            issue_type="ERROR",
            field="status",
            message=f"Invalid status: {scheme.status}",
            current_value=scheme.status,
            recommended_action="Use ACTIVE, INACTIVE, SUSPENDED, or UNKNOWN",
        ))

    # E6: Invalid eligibility rule operators
    for rule in scheme.eligibility_rules:
        try:
            RuleOperator(rule.operator)
        except ValueError:
            issues.append(ValidationIssue(
                scheme_id=scheme.scheme_id,
                issue_type="ERROR",
                field="eligibility_rules",
                message=f"Invalid rule operator: {rule.operator}",
                recommended_action="Use a valid RuleOperator",
            ))

    # E7: Invalid URL formats
    if scheme.official_url and not validate_url_format(scheme.official_url):
        issues.append(ValidationIssue(
            scheme_id=scheme.scheme_id,
            issue_type="ERROR",
            field="official_url",
            message=f"Malformed URL: {scheme.official_url}",
            current_value=scheme.official_url,
            recommended_action="Fix or remove malformed URL",
        ))

    if scheme.application_url and not validate_url_format(scheme.application_url):
        issues.append(ValidationIssue(
            scheme_id=scheme.scheme_id,
            issue_type="ERROR",
            field="application_url",
            message=f"Malformed URL: {scheme.application_url}",
            current_value=scheme.application_url,
            recommended_action="Fix or remove malformed URL",
        ))

    # === SOFT WARNINGS ===

    if not scheme.eligibility_summary:
        issues.append(ValidationIssue(
            scheme_id=scheme.scheme_id,
            issue_type="WARNING",
            field="eligibility_summary",
            message="Missing eligibility summary",
        ))

    if not scheme.benefits:
        issues.append(ValidationIssue(
            scheme_id=scheme.scheme_id,
            issue_type="WARNING",
            field="benefits",
            message="Missing benefits information",
        ))

    if not scheme.required_documents:
        issues.append(ValidationIssue(
            scheme_id=scheme.scheme_id,
            issue_type="WARNING",
            field="required_documents",
            message="Missing required documents list",
        ))

    if not scheme.application_steps:
        issues.append(ValidationIssue(
            scheme_id=scheme.scheme_id,
            issue_type="WARNING",
            field="application_steps",
            message="Missing application steps",
        ))

    if not scheme.application_url:
        issues.append(ValidationIssue(
            scheme_id=scheme.scheme_id,
            issue_type="WARNING",
            field="application_url",
            message="Missing application URL",
        ))

    if scheme.status == SchemeStatus.UNKNOWN:
        issues.append(ValidationIssue(
            scheme_id=scheme.scheme_id,
            issue_type="WARNING",
            field="status",
            message="Scheme status is UNKNOWN",
            recommended_action="Verify current status from official source",
        ))

    if scheme.possible_duplicate:
        issues.append(ValidationIssue(
            scheme_id=scheme.scheme_id,
            issue_type="WARNING",
            field="possible_duplicate",
            message="Flagged as possible duplicate",
            recommended_action="Verify and merge or differentiate",
        ))

    # Check source types — warn if only secondary sources
    has_official = any(
        sr.source_type.value.startswith("OFFICIAL")
        for sr in scheme.source_records
    )
    if scheme.source_records and not has_official:
        issues.append(ValidationIssue(
            scheme_id=scheme.scheme_id,
            issue_type="WARNING",
            field="source_records",
            message="Only secondary sources — no official source",
            recommended_action="Add official government source for verification",
        ))

    return issues


def generate_manual_review_queue(
    schemes: List[CanonicalScheme],
    report: ValidationReport,
) -> List[ManualReviewItem]:
    """Generate a manual review queue from validation results."""
    queue = []

    # Add schemes flagged for review
    for scheme in schemes:
        if scheme.needs_review:
            queue.append(ManualReviewItem(
                scheme_id=scheme.scheme_id,
                issue_type="NEEDS_REVIEW",
                explanation=scheme.review_notes or "Flagged for manual review",
                recommended_action="Verify scheme data against official source",
                source_url=scheme.official_url,
            ))

        if scheme.possible_duplicate:
            queue.append(ManualReviewItem(
                scheme_id=scheme.scheme_id,
                issue_type="POSSIBLE_DUPLICATE",
                explanation="This scheme may be a duplicate of another scheme",
                recommended_action="Compare with similar schemes and merge or differentiate",
                source_url=scheme.official_url,
            ))

    # Add issues from validation
    for issue in report.issues:
        if issue.issue_type == "WARNING" and issue.field in (
            "status", "eligibility_summary", "source_records"
        ):
            queue.append(ManualReviewItem(
                scheme_id=issue.scheme_id,
                issue_type=f"MISSING_{issue.field.upper()}" if "Missing" in issue.message else issue.message.upper().replace(" ", "_")[:30],
                field=issue.field,
                current_value=issue.current_value,
                explanation=issue.message,
                recommended_action=issue.recommended_action or "Verify and update",
            ))

    return queue
