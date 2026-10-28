"""
CLI script to import validated corpus into PostgreSQL.

Usage:
  python scripts/import_corpus.py              # Full import
  python scripts/import_corpus.py --dry-run    # Preview without modifying DB
  python scripts/import_corpus.py --force      # Import even with errors
  python scripts/import_corpus.py --allow-production  # Required for production env
"""

import sys
import os
import asyncio
import argparse

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.core.config import settings
from app.database.connection import init_db, close_db
from app.services.corpus_import_service import import_corpus, load_corpus


def main():
    parser = argparse.ArgumentParser(description="Import validated corpus into PostgreSQL")
    parser.add_argument("--dry-run", action="store_true", help="Preview without modifying DB")
    parser.add_argument("--force", action="store_true", help="Continue import even with errors")
    parser.add_argument("--allow-production", action="store_true", help="Required for production environment")
    parser.add_argument("--corpus", type=str, help="Path to schemes.json (auto-detected if omitted)")
    args = parser.parse_args()

    # Safety check for production
    if settings.ENVIRONMENT == "production" and not args.allow_production and not args.dry_run:
        print("ERROR: Production environment detected.")
        print("Use --allow-production to confirm, or --dry-run to preview.")
        sys.exit(1)

    # Display environment info (without credentials)
    db_url = settings.effective_database_url
    if db_url:
        # Mask password in URL for display
        display_url = db_url
        if "@" in display_url:
            parts = display_url.split("@")
            display_url = "***@" + parts[-1]
    else:
        display_url = "(not configured)"

    print(f"Environment: {settings.ENVIRONMENT}")
    print(f"Database: {display_url}")

    if args.dry_run:
        # Dry run doesn't need DB connection
        try:
            schemes, manifest = load_corpus(args.corpus)
            print(f"Corpus version: {manifest.get('version', '?')}")
            from app.services.corpus_import_service import _print_dry_run
            _print_dry_run(schemes, manifest.get("version", "1.0.0"), manifest)
        except Exception as e:
            print(f"ERROR: {e}")
            sys.exit(1)
        return

    if not db_url:
        print("ERROR: No DATABASE_URL configured. Set it in .env")
        sys.exit(1)

    asyncio.run(_do_import(args))


async def _do_import(args):
    """Run the async import."""
    await init_db()
    try:
        stats = await import_corpus(
            corpus_path=args.corpus,
            dry_run=False,
            force=args.force,
        )
        print(f"\nImport Report")
        print(f"=============")
        print(f"  Records read:     {stats.records_read}")
        print(f"  Inserted:         {stats.records_inserted}")
        print(f"  Updated:          {stats.records_updated}")
        print(f"  Skipped:          {stats.records_skipped}")
        print(f"  Errors:           {stats.errors}")
        print(f"  Warnings:         {stats.warnings}")

        if stats.errors > 0:
            print(f"\n  Error messages:")
            for msg in stats.error_messages[:10]:
                print(f"    - {msg}")
            sys.exit(1)
        else:
            print(f"\n[OK] Import completed successfully!")

    except Exception as e:
        print(f"\n[FAIL] Import failed: {e}")
        sys.exit(1)
    finally:
        await close_db()


if __name__ == "__main__":
    main()
