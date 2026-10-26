"""
Tests for the corpus schema (CanonicalScheme, EligibilityRule, etc.)
"""

import pytest
from app.ingestion import (
    CanonicalScheme, Benefit, EligibilityRule, RequiredDocument,
    ApplicationStep, SourceRecord, SchemeLevel, SchemeStatus,
    SourceType, RuleOperator, LogicalGroup, AadhaarRequirement,
    BenefitType, CorpusManifest, ValidationIssue,
)


class TestCanonicalScheme:
    """Test canonical scheme schema validation."""

    def test_valid_minimal_scheme(self):
        """A scheme with only required fields should be valid."""
        s = CanonicalScheme(
            scheme_id="TEST_001",
            name="Test Scheme",
            description="A test scheme.",
        )
        assert s.scheme_id == "TEST_001"
        assert s.name == "Test Scheme"
        assert s.status == SchemeStatus.UNKNOWN
        assert s.level == SchemeLevel.UNKNOWN

    def test_scheme_id_uppercased(self):
        """scheme_id should be normalized to uppercase."""
        s = CanonicalScheme(scheme_id="pm_kisan", name="Test", description="Test")
        assert s.scheme_id == "PM_KISAN"

    def test_scheme_id_empty_rejected(self):
        """Empty scheme_id should raise validation error."""
        with pytest.raises(Exception):
            CanonicalScheme(scheme_id="", name="Test", description="Test")

    def test_name_empty_rejected(self):
        """Empty name should raise validation error."""
        with pytest.raises(Exception):
            CanonicalScheme(scheme_id="TEST", name="", description="Test")

    def test_scheme_id_whitespace_stripped(self):
        """Whitespace in scheme_id should be stripped."""
        s = CanonicalScheme(scheme_id="  PM_KISAN  ", name="Test", description="Test")
        assert s.scheme_id == "PM_KISAN"

    def test_full_scheme(self):
        """A fully populated scheme should validate correctly."""
        s = CanonicalScheme(
            scheme_id="FULL_TEST",
            name="Full Test Scheme",
            short_name="FTS",
            aliases=["Test", "Full Test"],
            description="A fully populated test scheme.",
            detailed_description="Detailed description.",
            ministry="Ministry of Testing",
            department="Department of Tests",
            level=SchemeLevel.CENTRAL,
            scheme_type="income_support",
            status=SchemeStatus.ACTIVE,
            target_beneficiaries=["farmers"],
            applicable_states=["Karnataka"],
            benefits=[Benefit(type=BenefitType.FINANCIAL_ASSISTANCE, amount="Rs. 6000", description="Test benefit")],
            eligibility_summary="All farmers",
            eligibility_rules=[EligibilityRule(field="state", operator=RuleOperator.IN, value=["Karnataka"], source_text="Karnataka farmers")],
            required_documents=[RequiredDocument(name="Aadhaar", mandatory=True)],
            aadhaar_requirement=AadhaarRequirement.REQUIRED,
            application_steps=[ApplicationStep(step_number=1, description="Apply online", mode="online")],
            application_mode=["online"],
            application_url="https://example.gov.in/apply",
            official_url="https://example.gov.in",
            source_records=[SourceRecord(source_id="TEST", url="https://example.gov.in", source_type=SourceType.OFFICIAL_CENTRAL, retrieved_at="2026-01-01")],
            last_verified_at="2026-01-01",
            data_version="1.0",
        )
        assert s.scheme_id == "FULL_TEST"
        assert len(s.eligibility_rules) == 1
        assert s.eligibility_rules[0].operator == RuleOperator.IN
        assert len(s.benefits) == 1
        assert s.benefits[0].type == BenefitType.FINANCIAL_ASSISTANCE


class TestEligibilityRule:
    """Test eligibility rule schema."""

    def test_valid_rule(self):
        rule = EligibilityRule(field="state", operator=RuleOperator.IN, value=["Karnataka"])
        assert rule.field == "state"
        assert rule.operator == RuleOperator.IN

    def test_unknown_operator(self):
        """UNKNOWN operator for ambiguous rules."""
        rule = EligibilityRule(field="income", operator=RuleOperator.UNKNOWN, value=None, source_text="Small and marginal farmers")
        assert rule.operator == RuleOperator.UNKNOWN

    def test_between_operator(self):
        rule = EligibilityRule(field="age", operator=RuleOperator.BETWEEN, value=[18, 40])
        assert rule.value == [18, 40]

    def test_boolean_operator(self):
        rule = EligibilityRule(field="has_land", operator=RuleOperator.BOOLEAN, value=True)
        assert rule.value is True

    def test_logical_group_default(self):
        rule = EligibilityRule(field="state", operator=RuleOperator.EQ, value="Karnataka")
        assert rule.logical_group == LogicalGroup.AND

    def test_or_logical_group(self):
        rule = EligibilityRule(field="category", operator=RuleOperator.IN, value=["SC", "ST"], logical_group=LogicalGroup.OR)
        assert rule.logical_group == LogicalGroup.OR


class TestEnums:
    """Test enum values."""

    def test_scheme_status_values(self):
        assert SchemeStatus.ACTIVE.value == "ACTIVE"
        assert SchemeStatus.UNKNOWN.value == "UNKNOWN"

    def test_source_type_values(self):
        assert SourceType.OFFICIAL_CENTRAL.value == "OFFICIAL_CENTRAL"
        assert SourceType.SECONDARY.value == "SECONDARY"

    def test_rule_operator_values(self):
        ops = [o.value for o in RuleOperator]
        assert "EQ" in ops
        assert "IN" in ops
        assert "LTE" in ops
        assert "BETWEEN" in ops
        assert "UNKNOWN" in ops

    def test_benefit_type_values(self):
        assert BenefitType.FINANCIAL_ASSISTANCE.value == "financial_assistance"
        assert BenefitType.INSURANCE.value == "insurance"

    def test_invalid_enum_raises(self):
        with pytest.raises(ValueError):
            SchemeStatus("NONEXISTENT")
