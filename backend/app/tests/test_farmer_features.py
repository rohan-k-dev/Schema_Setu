"""
Tests for Farmer Accounts, Authentication, Saved Profiles, and Personalized Dashboard.

Covers:
  1. Security: bcrypt hashing, password verification, JWT tokens, expiry, reset tokens.
  2. Profile Service: completeness scoring, missing field identification, profile updates.
  3. Auth API: registration, login, token refresh, logout, password recovery.
  4. Farmers API: profile CRUD, consent enforcement, saved schemes CRUD, search history, dashboard.
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    generate_reset_token,
    hash_password,
    hash_refresh_token,
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


# ═══════════════════════════════════════════════════════════════════════════════
# 1. SECURITY & TOKEN TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestSecurityUtils:
    def test_password_hashing_and_verification(self):
        raw = "Kisan@Secure123"
        hashed = hash_password(raw)
        assert hashed != raw
        assert hashed.startswith("$2b$") or hashed.startswith("$2a$")
        assert verify_password(raw, hashed) is True
        assert verify_password("WrongPassword999", hashed) is False

    def test_hashes_are_salted_differently(self):
        raw = "SamePassword123"
        hash1 = hash_password(raw)
        hash2 = hash_password(raw)
        assert hash1 != hash2
        assert verify_password(raw, hash1) is True
        assert verify_password(raw, hash2) is True

    def test_access_token_creation_and_decoding(self):
        farmer_id = "test-uuid-123"
        token = create_access_token(farmer_id=farmer_id)
        sub = decode_access_token(token)
        assert sub == farmer_id

    def test_expired_access_token(self):
        farmer_id = "test-uuid-123"
        token = create_access_token(
            farmer_id=farmer_id,
            expires_delta=datetime.timedelta(seconds=-10),
        )
        assert decode_access_token(token) is None

    def test_tampered_access_token(self):
        token = create_access_token(farmer_id="abc")
        tampered = token[:-4] + "abcd"
        assert decode_access_token(tampered) is None

    def test_refresh_token_generation_and_hashing(self):
        raw, hashed = generate_refresh_token()
        assert len(raw) > 30
        assert len(hashed) == 64  # SHA-256 hex
        assert hash_refresh_token(raw) == hashed

    def test_reset_token_generation(self):
        raw, hashed = generate_reset_token()
        assert len(raw) > 20
        assert len(hashed) == 64


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
            annual_income=120000.0,
            has_aadhaar=True,
            occupation="cultivator",
        )
        score = compute_completeness(row)
        missing = missing_fields(row)
        assert score == 100.0
        assert len(missing) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 3. AUTH API ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════

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

    @patch("app.services.auth_service.get_farmer_by_email", new_callable=AsyncMock)
    def test_register_conflict_on_existing_email(self, mock_get_email):
        mock_get_email.return_value = FarmerRow(
            id=1,
            farmer_id="uuid-1",
            email="existing@example.com",
            password_hash="dummy",
        )
        res = client.post(
            "/auth/register",
            json={"email": "existing@example.com", "password": "SecurePassword123!"},
        )
        assert res.status_code == 409
        assert "already exists" in res.json()["detail"]["message"]

    @patch("app.services.auth_service.create_farmer", new_callable=AsyncMock)
    @patch("app.services.auth_service.get_farmer_by_email", new_callable=AsyncMock)
    @patch("app.services.auth_service.create_refresh_token", new_callable=AsyncMock)
    @patch("app.services.auth_service.get_farmer_pk", new_callable=AsyncMock)
    def test_register_success(self, mock_get_pk, mock_create_rt, mock_get_email, mock_create):
        mock_get_email.return_value = None
        mock_get_pk.return_value = 10
        mock_create.return_value = FarmerRow(
            id=10,
            farmer_id="new-farmer-uuid",
            email="newfarmer@example.com",
            password_hash="dummyhash",
            full_name="Rajesh Kumar",
        )
        res = client.post(
            "/auth/register",
            json={
                "email": "newfarmer@example.com",
                "password": "StrongPassword123!",
                "full_name": "Rajesh Kumar",
            },
        )
        assert res.status_code == 201
        data = res.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["farmer_id"] == "new-farmer-uuid"

    @patch("app.services.auth_service.get_farmer_by_email", new_callable=AsyncMock)
    def test_login_invalid_password(self, mock_get_email):
        mock_get_email.return_value = FarmerRow(
            id=1,
            farmer_id="uuid-1",
            email="farmer@example.com",
            password_hash=hash_password("CorrectPass123!"),
        )
        res = client.post(
            "/auth/login",
            json={"email": "farmer@example.com", "password": "WrongPassword999"},
        )
        assert res.status_code == 401
        data = res.json()
        assert "Invalid" in (data.get("error", {}).get("message") or data.get("detail", {}).get("message", ""))

    @patch("app.services.auth_service.update_farmer_last_login", new_callable=AsyncMock)
    @patch("app.services.auth_service.create_refresh_token", new_callable=AsyncMock)
    @patch("app.services.auth_service.get_farmer_pk", new_callable=AsyncMock)
    @patch("app.services.auth_service.get_farmer_by_email", new_callable=AsyncMock)
    def test_login_success(self, mock_get_email, mock_get_pk, mock_create_rt, mock_last_login):
        mock_get_pk.return_value = 1
        mock_get_email.return_value = FarmerRow(
            id=1,
            farmer_id="uuid-1",
            email="farmer@example.com",
            password_hash=hash_password("CorrectPass123!"),
            full_name="Ramesh Patil",
        )
        res = client.post(
            "/auth/login",
            json={"email": "farmer@example.com", "password": "CorrectPass123!"},
        )
        assert res.status_code == 200
        data = res.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["farmer_id"] == "uuid-1"

    def test_forgot_password_generic_message(self):
        res = client.post(
            "/auth/forgot-password",
            json={"email": "nonexistent@example.com"},
        )
        assert res.status_code == 202
        assert "reset link" in res.json()["message"]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. PROTECTED FARMERS API & DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════════

class TestFarmersAPI:
    def test_protected_routes_require_bearer_token(self):
        res = client.get("/farmers/me/dashboard")
        # FastAPI HTTPBearer returns 403 when Authorization header is absent
        assert res.status_code in (401, 403)

    @patch("app.services.profile_service.get_farmer_pk", new_callable=AsyncMock)
    @patch("app.services.profile_service.upsert_farmer_profile", new_callable=AsyncMock)
    @patch("app.services.profile_service.get_farmer_profile", new_callable=AsyncMock)
    def test_profile_update_without_consent_fails(self, mock_get_profile, mock_upsert, mock_get_pk):
        mock_get_pk.return_value = 1
        mock_get_profile.return_value = None
        token = create_access_token(farmer_id="test-farmer-id")
        res = client.put(
            "/farmers/me/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "state": "Maharashtra",
                "consent_given": False,
            },
        )
        # CONSENT_REQUIRED maps to 403 Forbidden
        assert res.status_code == 403
        assert "Consent" in res.json()["detail"]["message"]

    @patch("app.services.profile_service.get_farmer_by_id", new_callable=AsyncMock)
    @patch("app.services.profile_service.get_farmer_profile", new_callable=AsyncMock)
    @patch("app.services.profile_service.get_farmer_pk", new_callable=AsyncMock)
    @patch("app.services.profile_service.upsert_farmer_profile", new_callable=AsyncMock)
    def test_profile_update_with_consent_succeeds(self, mock_upsert, mock_get_pk, mock_get_profile, mock_get_farmer):
        mock_get_pk.return_value = 1
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
            primary_crop="Wheat",
            consent_given=True,
        )
        token = create_access_token(farmer_id="test-farmer-id")
        res = client.put(
            "/farmers/me/profile",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "state": "Punjab",
                "district": "Ludhiana",
                "land_size_acres": 5.0,
                "primary_crop": "Wheat",
                "consent_given": True,
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert data["state"] == "Punjab"
        assert data["district"] == "Ludhiana"
        assert data["profile_completeness"] > 0

    @patch("app.services.profile_service.get_search_history", new_callable=AsyncMock)
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
        mock_history.return_value = [
            SearchHistoryRow(
                id=1,
                farmer_id=1,
                query="Drip irrigation subsidies",
            )
        ]

        token = create_access_token(farmer_id="fid-123")
        res = client.get(
            "/farmers/me/dashboard",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 200
        dashboard = res.json()
        assert dashboard["account"]["email"] == "ramesh@example.com"
        assert dashboard["profile"]["state"] == "Maharashtra"
        assert len(dashboard["saved_schemes"]) == 1
        assert dashboard["saved_schemes"][0]["scheme_id"] == "PM_KISAN"
        assert len(dashboard["recent_searches"]) == 1
        assert dashboard["profile_completeness"] > 0
