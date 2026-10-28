"""
Tests for Farmer Accounts, Authentication, Saved Profiles, and Personalized Dashboard.

Covers:
  1. Security: Argon2id hashing, password verification, opaque token generation.
  2. Profile Service: completeness scoring, missing field identification, profile updates.
  3. Auth API: request validation (the full account flows are in test_auth_security.py).
  4. Farmers API: profile CRUD, consent enforcement, saved schemes CRUD, search history, dashboard.

Updated for server-managed cookie sessions: protected routes are exercised with a
dependency override of get_current_principal (a FARMER) instead of a bearer JWT.
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_principal
from app.core.permissions import Principal, Role, permissions_for
from app.core.security import (
    generate_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.main import app
from app.models.db.farmer_auth import (
    FarmerProfileRow,
    FarmerRow,
    SavedSchemeRow,
    SearchHistoryRow,
)
from app.services.profile_service import (
    compute_completeness,
    missing_fields,
)

client = TestClient(app)


def _signed_in_as(farmer_id: str):
    """Authenticate requests as FARMER *farmer_id* (replaces the former bearer-JWT helper).
    Routes check permissions on the principal (docs/RBAC.md), so that is what is overridden."""
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        role=Role.FARMER, label="test@example.com", account_pk=1, farmer_id=farmer_id,
        permissions=permissions_for(Role.FARMER))


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.pop(get_current_principal, None)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. SECURITY & TOKEN TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestSecurityUtils:
    def test_password_hashing_and_verification(self):
        raw = "Kisan@Secure123"
        hashed = hash_password(raw)
        assert hashed != raw
        assert hashed.startswith("$argon2id$")
        assert verify_password(raw, hashed) is True
        assert verify_password("WrongPassword999", hashed) is False

    def test_hashes_are_salted_differently(self):
        raw = "SamePassword123"
        hash1 = hash_password(raw)
        hash2 = hash_password(raw)
        assert hash1 != hash2
        assert verify_password(raw, hash1) is True
        assert verify_password(raw, hash2) is True

    def test_opaque_token_generation_and_hashing(self):
        raw, hashed = generate_token()
        assert len(raw) > 30
        assert len(hashed) == 64  # SHA-256 hex
        assert hash_token(raw) == hashed

    def test_tokens_are_unique(self):
        assert len({generate_token()[0] for _ in range(50)}) == 50


# ═══════════════════════════════════════════════════════════════════════════════
# 2. PROFILE SERVICE & COMPLETENESS TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestProfileService:
    def test_calculate_completeness_empty(self):
        assert compute_completeness(None) == 0.0
        missing = missing_fields(None)
        assert "state" in missing
        assert "land_size_acres" in missing
        assert "primary_crop" in missing

    def test_calculate_completeness_partial(self):
        row = FarmerProfileRow(
            id=1,
            farmer_id=1,
            state="Maharashtra",
            district="Pune",
            land_size_acres=3.5,
            primary_crop="Wheat",
        )
        score = compute_completeness(row)
        missing = missing_fields(row)
        assert 0 < score < 100
        assert "state" not in missing
        assert "land_size_acres" not in missing
        assert "primary_crop" not in missing
        assert len(missing) == 0  # all 3 critical fields are satisfied

    def test_calculate_completeness_full(self):
        row = FarmerProfileRow(
            id=1,
            farmer_id=1,
            state="Karnataka",
            district="Mandya",
            land_size_acres=2.0,
            primary_crop="Paddy",
            farming_type="irrigated",
            age=42,
            gender="male",
            category="small_farmer",
            income_range="1_to_2.5_lakh",
            residence="rural",
            occupation="cultivator",
        )
        score = compute_completeness(row)
        missing = missing_fields(row)
        assert score == 100.0
        assert len(missing) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 3. AUTH API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def _db_up(monkeypatch):
    """The auth endpoints answer 503 without a database; pretend one is configured."""
    monkeypatch.setattr("app.api.auth.is_db_available", lambda: True)
    monkeypatch.setattr("app.api.deps.is_db_available", lambda: True)


@pytest.mark.usefixtures("_db_up")
class TestAuthAPI:
    def test_register_weak_password_fails(self):
        res = client.post(
            "/auth/register",
            json={"email": "farmer@example.com", "password": "short", "full_name": "Test Farmer"},
        )
        assert res.status_code == 422

    def test_register_invalid_email_fails(self):
        res = client.post(
            "/auth/register",
            json={"email": "invalid-email", "password": "SecurePassword123!", "full_name": "Test Farmer"},
        )
        assert res.status_code == 422

    @patch("app.services.auth_service.repo.get_farmer_by_email", new_callable=AsyncMock)
    def test_forgot_password_generic_message(self, mock_get_email):
        mock_get_email.return_value = None
        res = client.post(
            "/auth/forgot-password",
            json={"email": "nonexistent@example.com"},
        )
        assert res.status_code == 202
        assert "If an account exists" in res.json()["message"]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. PROTECTED FARMERS API & DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

class TestFarmersAPI:
    def test_protected_routes_require_a_session(self, monkeypatch):
        monkeypatch.setattr("app.api.deps.is_db_available", lambda: True)
        res = client.get("/farmers/me/dashboard")
        assert res.status_code == 401

    @patch("app.services.profile_service.profile_repo.get_farmer_by_farmer_id", new_callable=AsyncMock)
    @patch("app.services.profile_service.profile_repo.save_profile", new_callable=AsyncMock)
    @patch("app.services.profile_service.profile_repo.get_profile", new_callable=AsyncMock)
    def test_profile_update_without_consent_fails(self, mock_get_profile, mock_save, mock_get_farmer):
        mock_get_farmer.return_value = FarmerRow(
            id=1, farmer_id="test-farmer-id", email="f@example.com", password_hash="h")
        mock_get_profile.return_value = None
        _signed_in_as("test-farmer-id")
        res = client.put(
            "/farmers/me/profile",
            json={
                "state": "Maharashtra",
                "consent_given": False,
            },
        )
        # CONSENT_REQUIRED maps to 403 Forbidden
        assert res.status_code == 403
        assert "Consent" in res.json()["detail"]["message"]
        mock_save.assert_not_called()

    @patch("app.services.profile_service.profile_repo.get_farmer_by_farmer_id", new_callable=AsyncMock)
    @patch("app.services.profile_service.profile_repo.get_profile", new_callable=AsyncMock)
    @patch("app.services.profile_service.profile_repo.save_profile", new_callable=AsyncMock)
    def test_profile_update_with_consent_succeeds(self, mock_upsert, mock_get_profile, mock_get_farmer):
        mock_get_profile.return_value = None
        mock_get_farmer.return_value = FarmerRow(
            id=1,
            farmer_id="test-farmer-id",
            email="punjabfarmer@example.com",
            password_hash="dummyhash",
            full_name="Harpreet Singh",
        )
        mock_upsert.return_value = FarmerProfileRow(
            id=1,
            farmer_id=1,
            state="Punjab",
            district="Ludhiana",
            land_size_acres=5.0,
            land_size_value=5.0,
            land_unit="acre",
            primary_crop="Wheat",
            consent_given=True,
        )
        _signed_in_as("test-farmer-id")
        res = client.put(
            "/farmers/me/profile",
            json={
                "state": "Punjab",
                "district": "Ludhiana",
                "land_size": 5.0,
                "land_unit": "acre",
                "primary_crop": "Wheat",
                "consent_given": True,
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["state"] == "Punjab"
        assert data["district"] == "Ludhiana"
        assert data["profile_completeness"] > 0

    @patch("app.services.profile_service.history_repo.list_page", new_callable=AsyncMock)
    @patch("app.services.profile_service.get_saved_schemes", new_callable=AsyncMock)
    @patch("app.services.profile_service.get_farmer_profile", new_callable=AsyncMock)
    @patch("app.services.profile_service.get_farmer_by_id", new_callable=AsyncMock)
    @patch("app.services.profile_service.get_farmer_pk", new_callable=AsyncMock)
    def test_dashboard_endpoint_aggregation(
        self,
        mock_get_pk,
        mock_get_farmer,
        mock_get_profile,
        mock_saved,
        mock_history,
    ):
        mock_get_pk.return_value = 1
        mock_get_farmer.return_value = FarmerRow(
            id=1,
            farmer_id="fid-123",
            email="ramesh@example.com",
            password_hash="dummyhash",
            full_name="Ramesh Patil",
        )
        mock_get_profile.return_value = FarmerProfileRow(
            id=1,
            farmer_id=1,
            state="Maharashtra",
            district="Pune",
            land_size_acres=2.5,
            primary_crop="Sugarcane",
            consent_given=True,
        )
        mock_saved.return_value = [
            SavedSchemeRow(
                id=1,
                farmer_id=1,
                scheme_id="PM_KISAN",
                scheme_name="PM-KISAN",
            )
        ]
        mock_history.return_value = ([
            SearchHistoryRow(
                id=1,
                farmer_id=1,
                query="Drip irrigation subsidies",
            )
        ], 1)

        _signed_in_as("fid-123")
        res = client.get("/farmers/me/dashboard")
        assert res.status_code == 200
        dashboard = res.json()
        assert dashboard["account"]["email"] == "ramesh@example.com"
        assert dashboard["profile"]["state"] == "Maharashtra"
        assert len(dashboard["saved_schemes"]) == 1
        assert dashboard["saved_schemes"][0]["scheme_id"] == "PM_KISAN"
        assert len(dashboard["recent_searches"]) == 1
        assert dashboard["profile_completeness"] > 0
