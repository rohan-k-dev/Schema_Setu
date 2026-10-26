"""
Validate corpus — standalone CLI script.

Usage:
    python scripts/validate_corpus.py
    python scripts/validate_corpus.py --corpus data/validated/schemes.json
"""

import sys
import os
import json
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.ingestion import CanonicalScheme
from app.ingestion.validator import validate_corpus, generate_manual_review_queue


def main():
    parser = argparse.ArgumentParser(description="Validate SchemeSetu corpus")
    parser.add_argument("--corpus", default=os.path.join(os.path.dirname(__file__), "..", "data", "validated", "schemes.json"),
                        help="Path to corpus JSON file")
    args = parser.parse_args()

    corpus_path = os.path.abspath(args.corpus)
    if not os.path.exists(corpus_path):
        print(f"ERROR: Corpus file not found: {corpus_path}")
        sys.exit(1)

    with open(corpus_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    schemes = [CanonicalScheme(**item) for item in data]
    report = validate_corpus(schemes)

    print(f"Corpus Validation Report")
    print(f"========================")
    print(f"Total schemes:       {report.total_schemes}")
    print(f"Valid:               {report.valid_schemes}")
    print(f"Failed:              {report.failed_schemes}")
    print(f"Errors:              {report.error_count}")
    print(f"Warnings:            {report.warning_count}")
    print(f"Duplicates:          {report.duplicate_count}")
    print(f"Rules count:         {report.rule_count}")
    print(f"Official source %:   {report.official_source_percentage}%")
    print(f"Review items:        {report.manual_review_count}")

    if report.missing_field_counts:
        print(f"\nMissing Fields:")
        for field, count in sorted(report.missing_field_counts.items()):
            print(f"  {field}: {count}")

    if report.error_count > 0:
        print(f"\nERRORS:")
        for issue in report.issues:
            if issue.issue_type == "ERROR":
                print(f"  [{issue.scheme_id}] {issue.field}: {issue.message}")

    if report.error_count == 0:
        print(f"\n[PASS] Corpus validation passed!")
    else:
        print(f"\n[FAIL] Corpus validation failed with {report.error_count} errors.")
        sys.exit(1)


if __name__ == "__main__":
    main()
