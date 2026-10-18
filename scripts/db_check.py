"""
Database verification script — checks DB health, migration, and data integrity.

Usage:
  python scripts/db_check.py
"""

import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.core.config import settings
from app.database.connection import init_db, close_db, get_db_connection, is_db_available


async def run_checks():
    """Run all database verification checks."""
    await init_db()

    if not is_db_available():
        print("Database: NOT CONNECTED")
        print("  Set DATABASE_URL in .env and try again.")
        await close_db()
        return False

    print("Database: CONNECTED")
    all_ok = True

    try:
        async with get_db_connection() as conn:
            async with conn.cursor() as cur:
                # Check alembic version
                try:
                    await cur.execute("SELECT version_num FROM alembic_version LIMIT 1")
                    row = await cur.fetchone()
                    version = row[0] if row else "NONE"
                    print(f"Migration: {version}")
                except Exception:
                    print("Migration: NOT RUN (alembic_version table missing)")
                    all_ok = False

                # Table counts
                tables = {
                    "schemes": "Schemes",
                    "scheme_aliases": "Aliases",
                    "scheme_states": "States",
                    "scheme_districts": "Districts",
                    "scheme_crops": "Crops",
                    "scheme_beneficiaries": "Beneficiaries",
                    "scheme_benefits": "Benefits",
                    "eligibility_rules": "Rules",
                    "scheme_documents": "Documents",
                    "application_steps": "Application steps",
                    "scheme_sources": "Sources",
                    "corpus_versions": "Corpus versions",
                    "ingestion_runs": "Ingestion runs",
                }

                for table, label in tables.items():
                    try:
                        await cur.execute(f"SELECT COUNT(*) FROM {table}")
                        row = await cur.fetchone()
                        count = row[0] if row else 0
                        print(f"{label}: {count}")
                    except Exception:
                        print(f"{label}: TABLE MISSING")
                        all_ok = False

                # Current corpus version
                try:
                    await cur.execute(
                        "SELECT version FROM corpus_versions ORDER BY id DESC LIMIT 1"
                    )
                    row = await cur.fetchone()
                    cv = row[0] if row else "NONE"
                    print(f"Current corpus: {cv}")
                except Exception:
                    print("Current corpus: UNKNOWN")

                # Integrity checks
                print("\n--- Integrity Checks ---")

                # Orphaned rules
                await cur.execute(
                    """SELECT COUNT(*) FROM eligibility_rules er
                       WHERE NOT EXISTS (SELECT 1 FROM schemes s WHERE s.id = er.scheme_id)"""
                )
                orphan_rules = (await cur.fetchone())[0]
                print(f"Orphaned rules: {orphan_rules}" + (" [OK]" if orphan_rules == 0 else " [FAIL]"))
                if orphan_rules > 0:
                    all_ok = False

                # Orphaned sources
                await cur.execute(
                    """SELECT COUNT(*) FROM scheme_sources ss
                       WHERE NOT EXISTS (SELECT 1 FROM schemes s WHERE s.id = ss.scheme_id)"""
                )
                orphan_src = (await cur.fetchone())[0]
                print(f"Orphaned sources: {orphan_src}" + (" [OK]" if orphan_src == 0 else " [FAIL]"))
                if orphan_src > 0:
                    all_ok = False

                # Orphaned documents
                await cur.execute(
                    """SELECT COUNT(*) FROM scheme_documents sd
                       WHERE NOT EXISTS (SELECT 1 FROM schemes s WHERE s.id = sd.scheme_id)"""
                )
                orphan_docs = (await cur.fetchone())[0]
                print(f"Orphaned documents: {orphan_docs}" + (" [OK]" if orphan_docs == 0 else " [FAIL]"))
                if orphan_docs > 0:
                    all_ok = False

                # Duplicate scheme_ids
                await cur.execute(
                    """SELECT scheme_id, COUNT(*) as cnt FROM schemes
                       GROUP BY scheme_id HAVING COUNT(*) > 1"""
                )
                dups = await cur.fetchall()
                print(f"Duplicate scheme_ids: {len(dups)}" + (" [OK]" if len(dups) == 0 else " [FAIL]"))
                if dups:
                    all_ok = False

                # Schemes without sources
                await cur.execute(
                    """SELECT COUNT(*) FROM schemes s
                       WHERE NOT EXISTS (SELECT 1 FROM scheme_sources WHERE scheme_id = s.id)"""
                )
                no_src = (await cur.fetchone())[0]
                print(f"Schemes without sources: {no_src}" + (" [OK]" if no_src == 0 else " [WARN]"))

    except Exception as e:
        print(f"\nIntegrity check error: {e}")
        all_ok = False
    finally:
        await close_db()

    print(f"\nIntegrity: {'PASS' if all_ok else 'FAIL'}")
    return all_ok


def main():
    ok = asyncio.run(run_checks())
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
