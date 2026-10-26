"""
Corpus Import Service — imports validated Phase 1 corpus into PostgreSQL.

Architecture:
  validated corpus (JSON) → import service → PostgreSQL

Key properties:
  - Transactional (all-or-nothing)
  - Idempotent (running twice produces same state)
  - Uses stable scheme_id as natural key for upserts
  - Records ingestion statistics
  - Supports dry-run mode
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from psycopg import sql

from app.database.connection import get_db_connection, is_db_available
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class ImportStats:
    """Tracks import statistics."""

    def __init__(self):
        self.records_read = 0
        self.records_inserted = 0
        self.records_updated = 0
        self.records_skipped = 0
        self.errors = 0
        self.warnings = 0
        self.error_messages: List[str] = []

    def to_dict(self) -> dict:
        return {
            "records_read": self.records_read,
            "records_inserted": self.records_inserted,
            "records_updated": self.records_updated,
            "records_skipped": self.records_skipped,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def _find_corpus_path() -> str:
    """Locate the validated corpus JSON file."""
    # Try relative to project root
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "validated", "schemes.json"),
        os.path.join(os.getcwd(), "data", "validated", "schemes.json"),
    ]
    for p in candidates:
        full = os.path.abspath(p)
        if os.path.exists(full):
            return full
    raise FileNotFoundError("Validated corpus not found. Run 'python scripts/build_corpus.py' first.")


def _find_manifest_path() -> Optional[str]:
    """Locate the corpus manifest."""
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "metadata", "corpus_manifest.json"),
        os.path.join(os.getcwd(), "data", "metadata", "corpus_manifest.json"),
    ]
    for p in candidates:
        full = os.path.abspath(p)
        if os.path.exists(full):
            return full
    return None


def manifest_version(manifest: dict) -> str:
    """The corpus version from the manifest (key ``corpus_version``; older files used ``version``)."""
    return manifest.get("corpus_version") or manifest.get("version") or "1.0.0"


def load_corpus(corpus_path: Optional[str] = None) -> tuple:
    """Load corpus data and manifest. Returns (schemes_list, manifest_dict)."""
    path = corpus_path or _find_corpus_path()
    with open(path, "r", encoding="utf-8") as f:
        schemes = json.load(f)

    manifest_path = _find_manifest_path()
    manifest = {}
    if manifest_path:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

    return schemes, manifest


async def import_corpus(
    corpus_path: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
) -> ImportStats:
    """
    Import validated corpus into PostgreSQL.

    Args:
        corpus_path: Path to schemes.json (auto-detected if None)
        dry_run: If True, validate and report but don't modify DB
        force: If True, allow import even with warnings
    """
    stats = ImportStats()

    # 1. Load corpus
    schemes, manifest = load_corpus(corpus_path)
    stats.records_read = len(schemes)
    corpus_version = manifest_version(manifest)   # was manifest.get("version"): the key is corpus_version
    schema_version = manifest.get("schema_version", "1.0.0")
    manifest_hash = manifest.get("content_hash", "")

    logger.info(f"Loaded {len(schemes)} schemes, corpus version {corpus_version}")

    if dry_run:
        _print_dry_run(schemes, corpus_version, manifest)
        return stats

    if not is_db_available():
        raise RuntimeError("Database not available. Set DATABASE_URL and start the application.")

    # 2. Import in a single transaction
    async with get_db_connection() as conn:
        try:
            async with conn.transaction():
                # 2a. Create/get corpus version
                cv_id = await _upsert_corpus_version(
                    conn, corpus_version, schema_version, manifest_hash, len(schemes)
                )

                # 2b. Create ingestion run
                run_id = await _create_ingestion_run(conn, cv_id)

                # 2c. Import each scheme
                for scheme_data in schemes:
                    try:
                        result = await _upsert_scheme(conn, scheme_data, cv_id)
                        if result == "inserted":
                            stats.records_inserted += 1
                        elif result == "updated":
                            stats.records_updated += 1
                        else:
                            stats.records_skipped += 1
                    except Exception as e:
                        stats.errors += 1
                        msg = f"Error importing {scheme_data.get('scheme_id', '?')}: {e}"
                        stats.error_messages.append(msg)
                        logger.error(msg)
                        if not force:
                            raise

                # 2d. Update ingestion run
                await _complete_ingestion_run(conn, run_id, stats)

            logger.info(
                f"Import complete: {stats.records_inserted} inserted, "
                f"{stats.records_updated} updated, {stats.records_skipped} skipped, "
                f"{stats.errors} errors"
            )

        except Exception as e:
            # Transaction auto-rolls back on exception
            logger.error(f"Import failed, transaction rolled back: {e}")
            raise

    return stats


def _print_dry_run(schemes: list, version: str, manifest: dict):
    """Print dry-run report."""
    print(f"\n[DRY RUN] Corpus Import Preview")
    print(f"  Corpus version: {version}")
    print(f"  Schemes: {len(schemes)}")

    scheme_ids = [s.get("scheme_id", "?") for s in schemes]
    unique_ids = set(scheme_ids)
    print(f"  Unique IDs: {len(unique_ids)}")
    if len(scheme_ids) != len(unique_ids):
        print(f"  WARNING: {len(scheme_ids) - len(unique_ids)} duplicate scheme_ids!")

    total_rules = sum(len(s.get("eligibility_rules", [])) for s in schemes)
    total_docs = sum(len(s.get("required_documents", [])) for s in schemes)
    total_steps = sum(len(s.get("application_steps", [])) for s in schemes)
    total_sources = sum(len(s.get("source_records", [])) for s in schemes)
    total_benefits = sum(len(s.get("benefits", [])) for s in schemes)

    print(f"  Eligibility rules: {total_rules}")
    print(f"  Documents: {total_docs}")
    print(f"  Application steps: {total_steps}")
    print(f"  Sources: {total_sources}")
    print(f"  Benefits: {total_benefits}")
    print(f"  No files written.\n")


async def _upsert_corpus_version(
    conn, version: str, schema_version: str, manifest_hash: str, scheme_count: int
) -> int:
    """Create or retrieve corpus version. Returns the corpus_version.id."""
    async with conn.cursor() as cur:
        # Check if version already exists
        await cur.execute(
            "SELECT id FROM corpus_versions WHERE version = %s", (version,)
        )
        row = await cur.fetchone()
        if row:
            return row[0]

        # Insert new version
        await cur.execute(
            """INSERT INTO corpus_versions (version, schema_version, generated_at, scheme_count, manifest_hash)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (version, schema_version, datetime.now(timezone.utc), scheme_count, manifest_hash),
        )
        row = await cur.fetchone()
        return row[0]


async def _create_ingestion_run(conn, corpus_version_id: int) -> int:
    """Create a new ingestion run record."""
    async with conn.cursor() as cur:
        await cur.execute(
            """INSERT INTO ingestion_runs (corpus_version_id, status)
               VALUES (%s, 'RUNNING') RETURNING id""",
            (corpus_version_id,),
        )
        row = await cur.fetchone()
        return row[0]


async def _complete_ingestion_run(conn, run_id: int, stats: ImportStats):
    """Update ingestion run with final stats."""
    status = "SUCCESS" if stats.errors == 0 else "PARTIAL"
    error_msg = "; ".join(stats.error_messages[:10]) if stats.error_messages else None
    async with conn.cursor() as cur:
        await cur.execute(
            """UPDATE ingestion_runs SET
                 completed_at = NOW(),
                 status = %s,
                 records_read = %s,
                 records_inserted = %s,
                 records_updated = %s,
                 records_skipped = %s,
                 errors = %s,
                 warnings = %s,
                 error_message = %s
               WHERE id = %s""",
            (status, stats.records_read, stats.records_inserted,
             stats.records_updated, stats.records_skipped,
             stats.errors, stats.warnings, error_msg, run_id),
        )


async def _upsert_scheme(conn, data: dict, cv_id: int) -> str:
    """
    Insert or update a single scheme and all its child records.
    Returns 'inserted', 'updated', or 'skipped'.
    """
    scheme_id = data["scheme_id"]

    async with conn.cursor() as cur:
        # Check if scheme exists
        await cur.execute("SELECT id FROM schemes WHERE scheme_id = %s", (scheme_id,))
        existing = await cur.fetchone()

        if existing:
            db_id = existing[0]
            # Update the scheme
            await cur.execute(
                """UPDATE schemes SET
                     name = %s, short_name = %s, description = %s,
                     detailed_description = %s, ministry = %s, department = %s,
                     level = %s, scheme_type = %s, status = %s,
                     eligibility_summary = %s, official_url = %s,
                     application_url = %s, application_mode = %s,
                     aadhaar_requirement = %s, data_version = %s,
                     last_verified_at = %s, possible_duplicate = %s,
                     needs_review = %s, review_notes = %s,
                     corpus_version_id = %s, updated_at = NOW()
                   WHERE id = %s""",
                (
                    data["name"], data.get("short_name"),
                    data["description"], data.get("detailed_description"),
                    data.get("ministry"), data.get("department"),
                    data.get("level", {}).get("value") if isinstance(data.get("level"), dict) else data.get("level"),
                    data.get("scheme_type"),
                    data.get("status", {}).get("value") if isinstance(data.get("status"), dict) else data.get("status", "ACTIVE"),
                    data.get("eligibility_summary"), data.get("official_url"),
                    data.get("application_url"),
                    json.dumps(data.get("application_mode")) if data.get("application_mode") else None,
                    data.get("aadhaar_requirement", {}).get("value") if isinstance(data.get("aadhaar_requirement"), dict) else data.get("aadhaar_requirement"),
                    data.get("data_version", "1.0"),
                    data.get("last_verified_at"),
                    data.get("possible_duplicate", False),
                    data.get("needs_review", False),
                    data.get("review_notes"),
                    cv_id, db_id,
                ),
            )
            # Delete old child records and re-insert (deterministic replacement)
            for table in [
                "scheme_aliases", "scheme_states", "scheme_districts",
                "scheme_crops", "scheme_beneficiaries", "scheme_benefits",
                "eligibility_rules", "scheme_documents", "application_steps",
                "scheme_sources",
            ]:
                # Table names come from the fixed list above; composed as SQL identifiers
                await cur.execute(
                    sql.SQL("DELETE FROM {} WHERE scheme_id = %s").format(sql.Identifier(table)),
                    (db_id,),
                )

            result = "updated"
        else:
            # Insert new scheme
            level_val = data.get("level")
            if isinstance(level_val, dict):
                level_val = level_val.get("value")
            status_val = data.get("status", "ACTIVE")
            if isinstance(status_val, dict):
                status_val = status_val.get("value", "ACTIVE")
            aadhaar_val = data.get("aadhaar_requirement")
            if isinstance(aadhaar_val, dict):
                aadhaar_val = aadhaar_val.get("value")

            await cur.execute(
                """INSERT INTO schemes (
                     scheme_id, name, short_name, description,
                     detailed_description, ministry, department,
                     level, scheme_type, status,
                     eligibility_summary, official_url, application_url,
                     application_mode, aadhaar_requirement, data_version,
                     last_verified_at, possible_duplicate, needs_review,
                     review_notes, corpus_version_id
                   ) VALUES (
                     %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                     %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                   ) RETURNING id""",
                (
                    scheme_id, data["name"], data.get("short_name"),
                    data["description"], data.get("detailed_description"),
                    data.get("ministry"), data.get("department"),
                    level_val, data.get("scheme_type"), status_val,
                    data.get("eligibility_summary"), data.get("official_url"),
                    data.get("application_url"),
                    json.dumps(data.get("application_mode")) if data.get("application_mode") else None,
                    aadhaar_val, data.get("data_version", "1.0"),
                    data.get("last_verified_at"),
                    data.get("possible_duplicate", False),
                    data.get("needs_review", False),
                    data.get("review_notes"), cv_id,
                ),
            )
            row = await cur.fetchone()
            db_id = row[0]
            result = "inserted"

        # Insert child records
        await _insert_aliases(cur, db_id, data)
        await _insert_states(cur, db_id, data)
        await _insert_districts(cur, db_id, data)
        await _insert_crops(cur, db_id, data)
        await _insert_beneficiaries(cur, db_id, data)
        await _insert_benefits(cur, db_id, data)
        await _insert_rules(cur, db_id, data)
        await _insert_documents(cur, db_id, data)
        await _insert_steps(cur, db_id, data)
        await _insert_sources(cur, db_id, data)

    return result


# ─── Child record inserters ─────────────────────────────────

async def _insert_aliases(cur, db_id: int, data: dict):
    aliases = data.get("aliases", [])
    if data.get("short_name") and data["short_name"] not in aliases:
        aliases = [data["short_name"]] + aliases
    for alias in aliases:
        if alias:
            await cur.execute(
                """INSERT INTO scheme_aliases (scheme_id, alias, normalized_alias)
                   VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
                (db_id, alias, alias.lower().strip()),
            )


async def _insert_states(cur, db_id: int, data: dict):
    states = data.get("applicable_states")
    if states:  # None means all states — no rows inserted
        for state in states:
            await cur.execute(
                """INSERT INTO scheme_states (scheme_id, state)
                   VALUES (%s, %s) ON CONFLICT DO NOTHING""",
                (db_id, state),
            )


async def _insert_districts(cur, db_id: int, data: dict):
    districts = data.get("applicable_districts")
    if districts:
        for district in districts:
            # District might be a string or dict
            if isinstance(district, dict):
                await cur.execute(
                    """INSERT INTO scheme_districts (scheme_id, state, district)
                       VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
                    (db_id, district.get("state", ""), district.get("district", "")),
                )
            else:
                await cur.execute(
                    """INSERT INTO scheme_districts (scheme_id, state, district)
                       VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
                    (db_id, "", str(district)),
                )


async def _insert_crops(cur, db_id: int, data: dict):
    crops = data.get("applicable_crops")
    if crops:  # None means all crops — no rows inserted
        for crop in crops:
            await cur.execute(
                """INSERT INTO scheme_crops (scheme_id, crop, normalized_crop)
                   VALUES (%s, %s, %s) ON CONFLICT DO NOTHING""",
                (db_id, crop, crop.lower().strip()),
            )


async def _insert_beneficiaries(cur, db_id: int, data: dict):
    for b in data.get("target_beneficiaries", []):
        if b:
            await cur.execute(
                """INSERT INTO scheme_beneficiaries (scheme_id, beneficiary_type)
                   VALUES (%s, %s) ON CONFLICT DO NOTHING""",
                (db_id, b),
            )


async def _insert_benefits(cur, db_id: int, data: dict):
    for i, benefit in enumerate(data.get("benefits", [])):
        btype = benefit.get("type", "unknown")
        if isinstance(btype, dict):
            btype = btype.get("value", "unknown")
        await cur.execute(
            """INSERT INTO scheme_benefits
                 (scheme_id, benefit_type, amount, currency, frequency,
                  condition, description, source_text, benefit_order)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                db_id, btype, benefit.get("amount"),
                benefit.get("currency", "INR"), benefit.get("frequency"),
                benefit.get("condition"), benefit.get("description", ""),
                benefit.get("source_text"), i,
            ),
        )


async def _insert_rules(cur, db_id: int, data: dict):
    for i, rule in enumerate(data.get("eligibility_rules", [])):
        operator = rule.get("operator", "UNKNOWN")
        if isinstance(operator, dict):
            operator = operator.get("value", "UNKNOWN")
        logical = rule.get("logical_group", "AND")
        if isinstance(logical, dict):
            logical = logical.get("value", "AND")
        await cur.execute(
            """INSERT INTO eligibility_rules
                 (scheme_id, rule_id, field_name, operator, value_json,
                  logical_group, required, source_text, unit,
                  original_value, original_unit, rule_order)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                db_id, rule.get("rule_id"), rule["field"],
                operator, json.dumps(rule.get("value")),
                logical, rule.get("required", True),
                rule.get("source_text"), rule.get("unit"),
                json.dumps(rule.get("original_value")) if rule.get("original_value") is not None else None,
                rule.get("original_unit"), i,
            ),
        )


async def _insert_documents(cur, db_id: int, data: dict):
    for i, doc in enumerate(data.get("required_documents", [])):
        await cur.execute(
            """INSERT INTO scheme_documents
                 (scheme_id, name, mandatory, description, source_text, document_order)
               VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
            (
                db_id, doc["name"], doc.get("mandatory", True),
                doc.get("description"), doc.get("source_text"), i,
            ),
        )


_STEP_MODE_TOKENS = {"online": "ONLINE", "offline": "OFFLINE", "csc": "CSC",
                     "office": "OFFICE", "bank": "OFFICE", "hybrid": "HYBRID"}


def normalize_step_mode(raw: Optional[str]) -> Optional[str]:
    """
    Map free-text corpus modes ("online/CSC/bank", "bank", ...) onto the
    schema's controlled vocabulary (ck_step_mode). Several channels → HYBRID;
    unrecognised → UNKNOWN. Phase 8: the corpus import used to fail on "BANK".
    """
    if not raw:
        return None
    parts = {p.strip().lower() for p in raw.replace(",", "/").split("/") if p.strip()}
    mapped = {_STEP_MODE_TOKENS.get(p, "UNKNOWN") for p in parts}
    if len(mapped) > 1:
        return "HYBRID"
    return mapped.pop() if mapped else None


async def _insert_steps(cur, db_id: int, data: dict):
    for step in data.get("application_steps", []):
        raw_mode = step.get("mode")
        mode = normalize_step_mode(raw_mode)
        notes = step.get("notes")
        if raw_mode and raw_mode.upper() != mode:
            notes = f"{notes} (mode: {raw_mode})" if notes else f"mode: {raw_mode}"
        await cur.execute(
            """INSERT INTO application_steps
                 (scheme_id, step_number, description, mode,
                  portal_name, portal_url, office_name, notes)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING""",
            (
                db_id, step.get("step_number", 0), step["description"],
                mode, step.get("portal_name"), step.get("portal_url"),
                step.get("office_name"), notes,
            ),
        )


async def _insert_sources(cur, db_id: int, data: dict):
    for i, src in enumerate(data.get("source_records", [])):
        stype = src.get("source_type", "UNKNOWN")
        if isinstance(stype, dict):
            stype = stype.get("value", "UNKNOWN")
        await cur.execute(
            """INSERT INTO scheme_sources
                 (scheme_id, source_id, url, source_type, source_name,
                  retrieved_at, verified_at, content_hash, reference_text, is_primary)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                db_id, src.get("source_id", "unknown"), src.get("url"),
                stype, src.get("source_name"),
                src.get("retrieved_at"), src.get("last_verified_at"),
                src.get("content_hash"), src.get("reference_text"),
                i == 0,  # First source is primary
            ),
        )
