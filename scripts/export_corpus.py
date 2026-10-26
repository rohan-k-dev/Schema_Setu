"""
Export corpus — standalone CLI script.

Usage:
    python scripts/export_corpus.py
    python scripts/export_corpus.py --dry-run
    python scripts/export_corpus.py --force
"""

import sys
import os
import json
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.ingestion import CanonicalScheme
from app.ingestion.validator import validate_corpus, generate_manual_review_queue
from app.ingestion.deduplicator import detect_duplicates, flag_duplicates
from app.ingestion.exporter import export_corpus


def main():
    parser = argparse.ArgumentParser(description="Export SchemeSetu corpus")
    parser.add_argument("--corpus", default=os.path.join(os.path.dirname(__file__), "..", "data", "validated", "schemes.json"))
    parser.add_argument("--dry-run", action="store_true", help="Show what would be exported without writing files")
    parser.add_argument("--force", action="store_true", help="Force re-export even if unchanged")
    parser.add_argument("--version", default="1.0.0", help="Corpus version string")
    args = parser.parse_args()

    corpus_path = os.path.abspath(args.corpus)
    if not os.path.exists(corpus_path):
        print(f"ERROR: Corpus file not found: {corpus_path}")
        sys.exit(1)

    with open(corpus_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    schemes = [CanonicalScheme(**item) for item in data]
    print(f"Loaded {len(schemes)} schemes from {corpus_path}")

    # Validate
    report = validate_corpus(schemes, corpus_version=args.version)
    review_queue = generate_manual_review_queue(schemes, report)

    if args.dry_run:
        print(f"\n[DRY RUN] Would export:")
        print(f"  Schemes: {len(schemes)}")
        print(f"  Valid: {report.valid_schemes}")
        print(f"  Errors: {report.error_count}")
        print(f"  Version: {args.version}")
        print(f"  No files written.")
        return

    if report.error_count > 0 and not args.force:
        print(f"\nERROR: {report.error_count} validation errors. Use --force to export anyway.")
        sys.exit(1)

    snapshot_dir = export_corpus(schemes, report, review_queue, corpus_version=args.version)
    print(f"\n[OK] Exported to {snapshot_dir}")
    print(f"  Schemes: {len(schemes)}")
    print(f"  Valid: {report.valid_schemes}")
    print(f"  Snapshot: {snapshot_dir}")


if __name__ == "__main__":
    main()
