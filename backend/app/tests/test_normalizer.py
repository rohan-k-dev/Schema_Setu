"""
Tests for normalizer functions.
"""

import pytest
from app.ingestion.normalizer import (
    normalize_state, normalize_states, normalize_crop, normalize_crops,
    normalize_category, normalize_gender, normalize_whitespace,
    normalize_url, validate_url_format, generate_scheme_id,
)


class TestStateNormalization:
    def test_exact_match(self):
        assert normalize_state("Karnataka") == "Karnataka"

    def test_case_insensitive(self):
        assert normalize_state("karnataka") == "Karnataka"

    def test_alias(self):
        assert normalize_state("KA") == "Karnataka"

    def test_alias_case(self):
        assert normalize_state("ka") == "Karnataka"

    def test_odisha_alias(self):
        assert normalize_state("Orissa") == "Odisha"

    def test_uttarakhand_alias(self):
        assert normalize_state("Uttaranchal") == "Uttarakhand"

    def test_unknown_returns_original(self):
        assert normalize_state("Unknown State") == "Unknown State"

    def test_empty(self):
        assert normalize_state("") is None

    def test_list(self):
        result = normalize_states(["KA", "TN", "Maharashtra"])
        assert result == ["Karnataka", "Tamil Nadu", "Maharashtra"]

    def test_dedup(self):
        result = normalize_states(["KA", "Karnataka", "ka"])
        assert result == ["Karnataka"]


class TestCropNormalization:
    def test_exact_match(self):
        assert normalize_crop("rice") == "rice"

    def test_alias(self):
        assert normalize_crop("finger millet") == "ragi"

    def test_paddy(self):
        assert normalize_crop("paddy") == "rice"

    def test_peanut(self):
        assert normalize_crop("peanut") == "groundnut"

    def test_unknown(self):
        result = normalize_crop("exotic_crop")
        assert result == "exotic_crop"

    def test_empty(self):
        assert normalize_crop("") is None


class TestCategoryNormalization:
    def test_sc(self):
        assert normalize_category("SC") == "SC"

    def test_scheduled_caste(self):
        assert normalize_category("Scheduled Caste") == "SC"

    def test_general(self):
        assert normalize_category("general") == "General"

    def test_ews(self):
        assert normalize_category("Economically Weaker Section") == "EWS"


class TestGenderNormalization:
    def test_male(self):
        assert normalize_gender("male") == "male"

    def test_women(self):
        assert normalize_gender("women") == "female"

    def test_all(self):
        assert normalize_gender("all") == "any"

    def test_unknown(self):
        assert normalize_gender("") == "unknown"


class TestWhitespaceNormalization:
    def test_multiple_spaces(self):
        assert normalize_whitespace("hello   world") == "hello world"

    def test_newlines(self):
        assert normalize_whitespace("hello\n\nworld") == "hello world"

    def test_leading_trailing(self):
        assert normalize_whitespace("  hello  ") == "hello"


class TestURLValidation:
    def test_valid_http(self):
        assert validate_url_format("http://example.gov.in") is True

    def test_valid_https(self):
        assert validate_url_format("https://pmkisan.gov.in") is True

    def test_no_scheme(self):
        assert validate_url_format("pmkisan.gov.in") is False

    def test_ftp(self):
        assert validate_url_format("ftp://example.com") is False

    def test_empty(self):
        assert validate_url_format("") is False

    def test_normalize_strips(self):
        result = normalize_url("  https://pmkisan.gov.in  ")
        assert result == "https://pmkisan.gov.in"

    def test_normalize_invalid(self):
        assert normalize_url("not-a-url") is None


class TestSchemeIDGeneration:
    def test_basic(self):
        result = generate_scheme_id("Kisan Credit Card")
        assert result == "KISAN_CREDIT_CARD"

    def test_strips_pm_prefix(self):
        result = generate_scheme_id("Pradhan Mantri Fasal Bima Yojana")
        assert "PRADHAN" not in result
        assert "FASAL_BIMA_YOJANA" in result

    def test_state_prefix(self):
        result = generate_scheme_id("Raitha Siri", level="state", state="Karnataka")
        assert result.startswith("STATE_KA_")

    def test_special_chars_removed(self):
        result = generate_scheme_id("Test (Special) Scheme!")
        assert "(" not in result
        assert "!" not in result

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            generate_scheme_id("")
