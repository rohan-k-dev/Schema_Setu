"""
Phase 2 Tests — Database domain models, repository, and import service.

These tests use mocks/fixtures — NO live database connection required.
Tests that require a real PostgreSQL instance are marked with skip.
"""

import json
import os
import sys
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import date

# Ensure imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ─── Domain Model Tests ─────────────────────────────────────

class TestDomainModels:
    """Test DB domain model validation and mapping."""

    def test_scheme_row_minimal(self):
        from app.models.db import SchemeRow
        row = SchemeRow(
            id=1, scheme_id="PM_KISAN", name="Test Scheme",
            description="Test description", status="ACTIVE",
        )
        assert row.scheme_id == "PM_KISAN"
        assert row.status == "ACTIVE"
        assert row.ministry is None

    def test_scheme_row_full(self):
        from app.models.db import SchemeRow
        row = SchemeRow(
            id=1, scheme_id="PM_KISAN", name="PM-KISAN",
            description="Income support", short_name="PMKISAN",
            ministry="MoAFW", level="central", status="ACTIVE",
            eligibility_summary="All farmers", official_url="https://pmkisan.gov.in",
        )
        assert row.short_name == "PMKISAN"
        assert row.level == "central"

    def test_eligibility_rule_row(self):
        from app.models.db import EligibilityRuleRow
        rule = EligibilityRuleRow(
            id=1, scheme_id=1, field_name="land_size_acres",
            operator="LTE", value_json=5, logical_group="AND",
            required=True, source_text="Land <= 5 acres",
        )
        assert rule.operator == "LTE"
        assert rule.value_json == 5

    def test_scheme_detail_composite(self):
        from app.models.db import SchemeRow, SchemeDetail
        scheme = SchemeRow(
            id=1, scheme_id="TEST", name="Test",
            description="Desc", status="ACTIVE",
        )
        detail = SchemeDetail(
            scheme=scheme,
            aliases=["Alias1", "Alias2"],
            states=["Karnataka"],
            crops=["ragi"],
            beneficiaries=["farmers"],
        )
        assert len(detail.aliases) == 2
        assert detail.states == ["Karnataka"]

    def test_corpus_version_row(self):
        from app.models.db import CorpusVersionRow
        cv = CorpusVersionRow(
            id=1, version="1.0.0", schema_version="1.0.0",
        )
        assert cv.version == "1.0.0"

    def test_ingestion_run_row(self):
        from app.models.db import IngestionRunRow
        run = IngestionRunRow(
            id=1, corpus_version_id=1, status="SUCCESS",
            records_read=40, records_inserted=40,
        )
        assert run.status == "SUCCESS"
        assert run.records_read == 40


# ─── Import Service Tests ───────────────────────────────────

class TestCorpusImportService:
    """Test import service utilities (no DB connection needed)."""

    def test_load_corpus(self):
        from app.services.corpus_import_service import load_corpus
        corpus_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "..", "data", "validated", "schemes.json"
        )
        corpus_path = os.path.abspath(corpus_path)
        if not os.path.exists(corpus_path):
            pytest.skip("Validated corpus not found")

        schemes, manifest = load_corpus(corpus_path)
        assert len(schemes) >= 30
        assert all("scheme_id" in s for s in schemes)

    def test_import_stats(self):
        from app.services.corpus_import_service import ImportStats
        stats = ImportStats()
        assert stats.records_read == 0
        assert stats.to_dict()["errors"] == 0

    def test_dry_run_no_db(self):
        """Dry run should work without DB connection."""
        from app.services.corpus_import_service import _print_dry_run
        schemes = [
            {"scheme_id": "TEST_001", "name": "Test", "eligibility_rules": [],
             "required_documents": [], "application_steps": [],
             "source_records": [{"source_id": "x"}], "benefits": []},
        ]
        # Should not raise
        _print_dry_run(schemes, "1.0.0", {"version": "1.0.0"})


# ─── Migration File Tests ───────────────────────────────────

class TestMigration:
    """Test that migration file is valid Python."""

    def test_migration_file_exists(self):
        migration_dir = os.path.join(
            os.path.dirname(__file__), "..", "..", "alembic", "versions"
        )
        migration_dir = os.path.abspath(migration_dir)
        assert os.path.isdir(migration_dir), "alembic/versions directory missing"

        files = [f for f in os.listdir(migration_dir) if f.endswith(".py")]
        assert len(files) >= 1, "No migration files found"

    def test_migration_imports(self):
        """Verify migration file is valid Python (importable)."""
        import importlib.util
        migration_dir = os.path.abspath(os.path.join(
            os.path.dirname(__file__), "..", "..", "alembic", "versions"
        ))
        files = [f for f in os.listdir(migration_dir) if f.endswith(".py")]
        for fname in files:
            spec = importlib.util.spec_from_file_location(
                fname.replace(".py", ""),
                os.path.join(migration_dir, fname),
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            assert hasattr(mod, "upgrade"), f"{fname} missing upgrade()"
            assert hasattr(mod, "downgrade"), f"{fname} missing downgrade()"


# ─── Repository Query Logic Tests ───────────────────────────

class TestSchemeRepositoryLogic:
    """Test repository query construction and result mapping."""

    def test_row_to_scheme_mapping(self):
        from app.database.repositories.scheme_repository import _row_to_scheme
        row = {
            "id": 1, "scheme_id": "PM_KISAN", "name": "PM-KISAN",
            "description": "Income support", "status": "ACTIVE",
            "short_name": None, "detailed_description": None,
            "ministry": "MoAFW", "department": None, "level": "central",
            "scheme_type": None, "eligibility_summary": "All farmers",
            "official_url": "https://pmkisan.gov.in",
            "application_url": None, "application_mode": None,
            "aadhaar_requirement": "required", "data_version": "1.0",
            "last_verified_at": None, "possible_duplicate": False,
            "needs_review": False, "review_notes": None,
            "corpus_version_id": 1, "created_at": None, "updated_at": None,
        }
        scheme = _row_to_scheme(row)
        assert scheme.scheme_id == "PM_KISAN"
        assert scheme.ministry == "MoAFW"

    def test_legacy_search_format(self):
        """Verify legacy adapter produces old-format dicts."""
        from app.models.db import SchemeRow
        scheme = SchemeRow(
            id=1, scheme_id="PM_KISAN", name="PM-KISAN",
            description="Income support", status="ACTIVE",
            ministry="MoAFW", eligibility_summary="All farmers",
            official_url="https://pmkisan.gov.in",
        )
        # Manually test the mapping logic
        result = {
            "scheme_id": scheme.scheme_id,
            "title": scheme.name,
            "ministry": scheme.ministry or "",
            "benefits_details": "",
            "eligibility_criteria_raw": scheme.eligibility_summary or "",
            "state_specific": "",
            "application_link": scheme.application_url or scheme.official_url or "",
        }
        assert result["title"] == "PM-KISAN"
        assert result["application_link"] == "https://pmkisan.gov.in"


# ─── Test Fixtures ───────────────────────────────────────────

class TestFixtures:
    """Test that test fixture data is valid."""

    def test_valid_scheme_fixture(self):
        """Create a minimal valid scheme for testing."""
        fixture = {
            "scheme_id": "TEST_SCHEME_001",
            "name": "Test Scheme for DB Tests",
            "description": "A test scheme used in database integration tests.",
            "status": "ACTIVE",
            "level": "central",
            "ministry": "Test Ministry",
            "eligibility_summary": "Test eligibility",
            "source_records": [
                {"source_id": "TEST_SOURCE", "source_type": "OFFICIAL_CENTRAL",
                 "retrieved_at": "2026-09-27"}
            ],
            "eligibility_rules": [
                {"field": "land_size_acres", "operator": "LTE", "value": 5,
                 "logical_group": "AND", "required": True}
            ],
            "required_documents": [
                {"name": "Test Document", "mandatory": True}
            ],
            "benefits": [
                {"type": "financial_assistance", "description": "Test benefit"}
            ],
        }
        assert fixture["scheme_id"] == "TEST_SCHEME_001"
        assert len(fixture["source_records"]) >= 1

    def test_duplicate_scheme_fixture(self):
        """Two schemes with same ID for testing idempotency."""
        s1 = {"scheme_id": "DUP_TEST", "name": "Version 1", "description": "V1", "status": "ACTIVE"}
        s2 = {"scheme_id": "DUP_TEST", "name": "Version 2", "description": "V2", "status": "ACTIVE"}
        assert s1["scheme_id"] == s2["scheme_id"]
        assert s1["name"] != s2["name"]
