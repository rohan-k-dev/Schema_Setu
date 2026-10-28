"""
Exporter — generates validated corpus files, snapshots, and reports.
"""

import json
import hashlib
import os
import shutil
from typing import List
from datetime import datetime

from app.ingestion import (
    CanonicalScheme, CorpusManifest, ValidationReport,
    ManualReviewItem, SchemeStatus,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

# Project root for data paths
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DATA_ROOT = os.path.join(PROJECT_ROOT, "data")


def export_corpus(
    schemes: List[CanonicalScheme],
    report: ValidationReport,
    review_queue: List[ManualReviewItem],
    corpus_version: str = "1.0.0",
) -> str:
    """
    Export the full validated corpus to the data directory.

    Creates:
    - data/normalized/schemes.json
    - data/validated/schemes.json
    - data/validated/validation_report.json
    - data/validated/validation_report.md
    - data/validated/manual_review_queue.json
    - data/metadata/corpus_manifest.json
    - data/snapshots/YYYY-MM-DD/schemes.json

    Returns the snapshot directory path.
    """
    # Sort schemes by ID for deterministic output
    schemes_sorted = sorted(schemes, key=lambda s: s.scheme_id)

    # Serialize
    schemes_data = [s.model_dump(mode="json") for s in schemes_sorted]
    schemes_json = json.dumps(schemes_data, indent=2, ensure_ascii=False)

    # Content hash
    content_hash = hashlib.sha256(schemes_json.encode()).hexdigest()[:16]

    # === Write normalized ===
    normalized_dir = os.path.join(DATA_ROOT, "normalized")
    os.makedirs(normalized_dir, exist_ok=True)
    _write_json(os.path.join(normalized_dir, "schemes.json"), schemes_data)

    # === Write validated ===
    validated_dir = os.path.join(DATA_ROOT, "validated")
    os.makedirs(validated_dir, exist_ok=True)
    _write_json(os.path.join(validated_dir, "schemes.json"), schemes_data)

    # Validation report JSON
    report_data = report.model_dump(mode="json")
    _write_json(os.path.join(validated_dir, "validation_report.json"), report_data)

    # Validation report Markdown
    md_report = _generate_markdown_report(report, schemes_sorted)
    with open(os.path.join(validated_dir, "validation_report.md"), "w", encoding="utf-8") as f:
        f.write(md_report)

    # Manual review queue
    review_data = [r.model_dump(mode="json") for r in review_queue]
    _write_json(os.path.join(validated_dir, "manual_review_queue.json"), review_data)

    # === Manifest ===
    metadata_dir = os.path.join(DATA_ROOT, "metadata")
    os.makedirs(metadata_dir, exist_ok=True)

    all_states = set()
    for s in schemes_sorted:
        if s.applicable_states:
            all_states.update(s.applicable_states)

    manifest = CorpusManifest(
        corpus_version=corpus_version,
        generated_at=datetime.utcnow().isoformat(),
        total_scheme_count=len(schemes_sorted),
        active_scheme_count=sum(1 for s in schemes_sorted if s.status == SchemeStatus.ACTIVE),
        source_count=sum(len(s.source_records) for s in schemes_sorted),
        official_source_count=sum(
            1 for s in schemes_sorted
            for sr in s.source_records
            if sr.source_type.value.startswith("OFFICIAL")
        ),
        domains=["agriculture", "farmer_welfare", "rural_development"],
        states=sorted(all_states),
        validation_status="passed" if report.error_count == 0 else "failed",
        content_hash=content_hash,
    )
    _write_json(os.path.join(metadata_dir, "corpus_manifest.json"), manifest.model_dump(mode="json"))

    # === Snapshot ===
    today = datetime.utcnow().strftime("%Y-%m-%d")
    snapshot_dir = os.path.join(DATA_ROOT, "snapshots", today)
    os.makedirs(snapshot_dir, exist_ok=True)
    _write_json(os.path.join(snapshot_dir, "schemes.json"), schemes_data)
    _write_json(os.path.join(snapshot_dir, "manifest.json"), manifest.model_dump(mode="json"))

    logger.info(f"Corpus exported: {len(schemes_sorted)} schemes, snapshot={today}, hash={content_hash}")
    return snapshot_dir


def _write_json(path: str, data: object) -> None:
    """Write JSON to file with consistent formatting."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _generate_markdown_report(report: ValidationReport, schemes: List[CanonicalScheme]) -> str:
    """Generate a human-readable markdown validation report."""
    lines = [
        "# Corpus Validation Report",
        "",
        f"**Generated**: {report.generated_at}",
        f"**Corpus Version**: {report.corpus_version}",
        "",
        "## Summary",
        "",
        f"| Metric | Value |",
        f"|---|---|",
        f"| Total Schemes | {report.total_schemes} |",
        f"| Valid Schemes | {report.valid_schemes} |",
        f"| Failed Schemes | {report.failed_schemes} |",
        f"| Errors | {report.error_count} |",
        f"| Warnings | {report.warning_count} |",
        f"| Duplicates | {report.duplicate_count} |",
        f"| Eligibility Rules | {report.rule_count} |",
        f"| Official Source % | {report.official_source_percentage}% |",
        f"| Manual Review Items | {report.manual_review_count} |",
        "",
    ]

    if report.missing_field_counts:
        lines.append("## Missing Fields")
        lines.append("")
        lines.append("| Field | Count |")
        lines.append("|---|---|")
        for field, count in sorted(report.missing_field_counts.items()):
            lines.append(f"| {field} | {count} |")
        lines.append("")

    if report.issues:
        errors = [i for i in report.issues if i.issue_type == "ERROR"]
        warnings = [i for i in report.issues if i.issue_type == "WARNING"]

        if errors:
            lines.append("## Errors")
            lines.append("")
            for issue in errors:
                lines.append(f"- **{issue.scheme_id}** [{issue.field}]: {issue.message}")
            lines.append("")

        if warnings:
            lines.append("## Warnings")
            lines.append("")
            for issue in warnings[:50]:  # Limit to 50
                lines.append(f"- **{issue.scheme_id}** [{issue.field}]: {issue.message}")
            if len(warnings) > 50:
                lines.append(f"- ... and {len(warnings) - 50} more warnings")
            lines.append("")

    lines.append("## Scheme List")
    lines.append("")
    lines.append("| # | ID | Name | Status | Sources | Rules |")
    lines.append("|---|---|---|---|---|---|")
    for idx, s in enumerate(schemes, 1):
        lines.append(f"| {idx} | {s.scheme_id} | {s.name} | {s.status.value} | {len(s.source_records)} | {len(s.eligibility_rules)} |")

    return "\n".join(lines)
