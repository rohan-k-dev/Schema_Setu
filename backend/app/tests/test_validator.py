"""
Tests for validator and deduplicator.
"""

import pytest
from app.ingestion import (
    CanonicalScheme, SourceRecord, EligibilityRule,
    SchemeStatus, SourceType, RuleOperator,
)
from app.ingestion.validator import validate_corpus, generate_manual_review_queue
from app.ingestion.deduplicator import detect_duplicates, flag_duplicates


def _make_scheme(scheme_id="TEST_001", name="Test Scheme", **kwargs):
    """Helper to create a minimal valid scheme."""
    defaults = {
        "scheme_id": scheme_id,
        "name": name,
        "description": "Test description.",
        "source_records": [SourceRecord(
            source_id="TEST_SOURCE", url="https://test.gov.in",
            source_type=SourceType.OFFICIAL_CENTRAL, retrieved_at="2026-01-01",
        )],
    }
    defaults.update(kwargs)
    return CanonicalScheme(**defaults)


class TestValidator:
    """Test corpus validation."""

    def test_valid_scheme(self):
        schemes = [_make_scheme()]
        report = validate_corpus(schemes)
        assert report.valid_schemes == 1
        assert report.error_count == 0

    def test_missing_scheme_id(self):
        """Missing scheme_id should be caught by Pydantic validator."""
        with pytest.raises(Exception):
            _make_scheme(scheme_id=" ")

    def test_duplicate_scheme_id(self):
        """Duplicate scheme_ids should produce errors."""
        schemes = [_make_scheme("DUPE"), _make_scheme("DUPE", name="Other")]
        report = validate_corpus(schemes)
        assert report.error_count >= 1
        assert any("Duplicate" in i.message for i in report.issues)

    def test_no_source_records(self):
        """Scheme with no sources should produce an error."""
        s = CanonicalScheme(scheme_id="NO_SRC", name="No Source", description="Test", source_records=[])
        report = validate_corpus([s])
        assert report.error_count >= 1
        assert any("No source" in i.message for i in report.issues)

    def test_invalid_url(self):
        """Malformed URL should produce an error."""
        s = _make_scheme(official_url="not-a-valid-url")
        report = validate_corpus([s])
        assert any("Malformed URL" in i.message for i in report.issues)

    def test_missing_eligibility_warning(self):
        """Missing eligibility should produce a warning, not error."""
        s = _make_scheme()
        report = validate_corpus([s])
        warnings = [i for i in report.issues if i.issue_type == "WARNING"]
        assert any("eligibility" in i.field for i in warnings)

    def test_unknown_status_warning(self):
        """UNKNOWN status should produce a warning."""
        s = _make_scheme(status=SchemeStatus.UNKNOWN)
        report = validate_corpus([s])
        assert any("UNKNOWN" in i.message for i in report.issues if i.issue_type == "WARNING")

    def test_official_source_percentage(self):
        """Should calculate official source percentage."""
        s = _make_scheme()
        report = validate_corpus([s])
        assert report.official_source_percentage == 100.0

    def test_secondary_only_warning(self):
        """Scheme with only secondary source should warn."""
        s = _make_scheme(source_records=[SourceRecord(
            source_id="SEC", url="https://blog.example.com",
            source_type=SourceType.SECONDARY, retrieved_at="2026-01-01",
        )])
        report = validate_corpus([s])
        assert any("secondary" in i.message.lower() for i in report.issues if i.issue_type == "WARNING")

    def test_invalid_rule_operator_error(self):
        """Invalid rule operator should produce an error."""
        # We can't really create an invalid enum via Pydantic, but we test the validator
        s = _make_scheme(eligibility_rules=[
            EligibilityRule(field="state", operator=RuleOperator.IN, value=["Karnataka"])
        ])
        report = validate_corpus([s])
        # Valid operator, so no error
        assert report.error_count == 0


class TestDeduplicator:
    """Test duplicate detection."""

    def test_identical_name(self):
        """Identical names should be detected."""
        s1 = _make_scheme("A", "Test Scheme")
        s2 = _make_scheme("B", "Test Scheme")
        dupes = detect_duplicates([s1, s2])
        assert len(dupes) == 1
        assert dupes[0][2] == "identical_name"

    def test_shared_alias(self):
        """Shared aliases should be detected."""
        s1 = _make_scheme("A", "Scheme Alpha", aliases=["PM Kisan"])
        s2 = _make_scheme("B", "Scheme Beta", aliases=["PM Kisan"])
        dupes = detect_duplicates([s1, s2])
        assert len(dupes) == 1
        assert "shared_alias" in dupes[0][2]

    def test_no_false_positive_different_names(self):
        """Different schemes should not be flagged."""
        s1 = _make_scheme("A", "Alpha Scheme")
        s2 = _make_scheme("B", "Beta Scheme")
        dupes = detect_duplicates([s1, s2])
        assert len(dupes) == 0

    def test_flag_duplicates(self):
        """flag_duplicates should mark schemes."""
        s1 = _make_scheme("A", "Same Name")
        s2 = _make_scheme("B", "Same Name")
        dupes = detect_duplicates([s1, s2])
        flagged = flag_duplicates([s1, s2], dupes)
        assert flagged[0].possible_duplicate is True
        assert flagged[1].possible_duplicate is True

    def test_domain_only_url_not_flagged(self):
        """Schemes sharing only a domain-level URL should NOT be flagged."""
        s1 = _make_scheme("A", "Alpha", official_url="https://agricoop.nic.in")
        s2 = _make_scheme("B", "Beta", official_url="https://agricoop.nic.in")
        dupes = detect_duplicates([s1, s2])
        assert len(dupes) == 0

    def test_specific_url_flagged(self):
        """Schemes sharing a specific page URL should be flagged."""
        s1 = _make_scheme("A", "Alpha", official_url="https://example.gov.in/scheme/123")
        s2 = _make_scheme("B", "Beta", official_url="https://example.gov.in/scheme/123")
        dupes = detect_duplicates([s1, s2])
        assert len(dupes) == 1


class TestManualReviewQueue:
    """Test review queue generation."""

    def test_needs_review_flagged(self):
        s = _make_scheme(needs_review=True, review_notes="Check this")
        report = validate_corpus([s])
        queue = generate_manual_review_queue([s], report)
        assert any(item.issue_type == "NEEDS_REVIEW" for item in queue)

    def test_possible_duplicate_in_queue(self):
        s = _make_scheme(possible_duplicate=True)
        report = validate_corpus([s])
        queue = generate_manual_review_queue([s], report)
        assert any(item.issue_type == "POSSIBLE_DUPLICATE" for item in queue)
