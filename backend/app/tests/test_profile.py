"""
Tests for FarmerProfile model — validation, merge behavior, completeness checking.

These tests run WITHOUT any external API keys or database connection.
"""

import pytest
from app.models.profile import FarmerProfile


class TestFarmerProfileValidation:
    """Test FarmerProfile creation and field validation."""

    def test_empty_profile(self):
        """An empty profile should have all fields as None."""
        profile = FarmerProfile()
        assert profile.state is None
        assert profile.land_size_acres is None
        assert profile.primary_crop is None

    def test_partial_profile(self):
        """A partial profile should accept provided fields."""
        profile = FarmerProfile(state="Karnataka", primary_crop="ragi")
        assert profile.state == "Karnataka"
        assert profile.primary_crop == "ragi"
        assert profile.land_size_acres is None

    def test_full_profile(self):
        """A complete profile should store all fields."""
        profile = FarmerProfile(
            state="Karnataka",
            district="Tumkur",
            land_size_acres=2.5,
            primary_crop="ragi",
            annual_income=120000,
            category="General",
            gender="Male",
            has_aadhaar=True,
        )
        assert profile.state == "Karnataka"
        assert profile.land_size_acres == 2.5


class TestFarmerProfileCompleteness:
    """Test deterministic completeness checking."""

    def test_all_missing(self):
        """Empty profile should report all critical fields missing."""
        profile = FarmerProfile()
        missing = profile.get_missing_critical_fields()
        assert missing == ["state", "land_size_acres", "primary_crop"]

    def test_partial_missing(self):
        """Profile with some fields should only list missing ones."""
        profile = FarmerProfile(state="Karnataka", primary_crop="ragi")
        missing = profile.get_missing_critical_fields()
        assert missing == ["land_size_acres"]

    def test_none_missing(self):
        """Complete profile should have no missing fields."""
        profile = FarmerProfile(state="Karnataka", land_size_acres=2, primary_crop="ragi")
        missing = profile.get_missing_critical_fields()
        assert missing == []

    def test_priority_order(self):
        """Missing fields should always follow priority: state → land → crop."""
        profile = FarmerProfile(land_size_acres=2)
        missing = profile.get_missing_critical_fields()
        assert missing == ["state", "primary_crop"]
        # state should be first
        assert missing[0] == "state"


class TestFarmerProfileMerge:
    """Test profile merging — the core multi-turn conversation behavior."""

    def test_merge_new_fields(self):
        """Merge should add new fields without overwriting existing ones."""
        existing = FarmerProfile(state="Karnataka")
        new_data = FarmerProfile(primary_crop="ragi")
        merged = existing.merge_with(new_data)
        assert merged.state == "Karnataka"
        assert merged.primary_crop == "ragi"

    def test_merge_preserves_existing_on_none(self):
        """None values in new data should NOT erase existing values."""
        existing = FarmerProfile(state="Karnataka", primary_crop="ragi")
        new_data = FarmerProfile(land_size_acres=2)
        merged = existing.merge_with(new_data)
        assert merged.state == "Karnataka"
        assert merged.primary_crop == "ragi"
        assert merged.land_size_acres == 2

    def test_merge_overwrites_with_new_value(self):
        """Non-None values in new data should overwrite existing values."""
        existing = FarmerProfile(state="Karnataka")
        new_data = FarmerProfile(state="Tamil Nadu")
        merged = existing.merge_with(new_data)
        assert merged.state == "Tamil Nadu"

    def test_merge_accumulates_across_turns(self):
        """Simulates multi-turn: Turn 1 → state, Turn 2 → crop, Turn 3 → land."""
        profile = FarmerProfile()

        # Turn 1
        turn1 = FarmerProfile(state="Karnataka")
        profile = profile.merge_with(turn1)
        assert profile.state == "Karnataka"
        assert profile.get_missing_critical_fields() == ["land_size_acres", "primary_crop"]

        # Turn 2
        turn2 = FarmerProfile(primary_crop="ragi")
        profile = profile.merge_with(turn2)
        assert profile.state == "Karnataka"
        assert profile.primary_crop == "ragi"
        assert profile.get_missing_critical_fields() == ["land_size_acres"]

        # Turn 3
        turn3 = FarmerProfile(land_size_acres=2)
        profile = profile.merge_with(turn3)
        assert profile.state == "Karnataka"
        assert profile.primary_crop == "ragi"
        assert profile.land_size_acres == 2
        assert profile.get_missing_critical_fields() == []

    def test_merge_llm_failure_preserves_profile(self):
        """If extraction returns None values, existing profile stays intact."""
        existing = FarmerProfile(state="Karnataka", primary_crop="ragi")
        empty_extraction = FarmerProfile()
        merged = existing.merge_with(empty_extraction)
        assert merged.state == "Karnataka"
        assert merged.primary_crop == "ragi"
