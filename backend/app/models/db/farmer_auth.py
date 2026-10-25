"""
Database domain models for farmer authentication, profiles, saved schemes,
and search history — introduced in Phase 9 (feature/farmer-auth-profile-dashboard).

These Pydantic models mirror the DB rows returned by FarmerRepository.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, List, Optional

from pydantic import BaseModel, EmailStr


class FarmerRow(BaseModel):
    """Represents a row in the ``farmers`` table."""

    id: int
    farmer_id: str          # UUID string
    email: str
    phone: Optional[str] = None
    full_name: Optional[str] = None
    password_hash: str
    is_active: bool = True
    is_verified: bool = False
    email_verified_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None
    login_count: int = 0
    password_reset_token: Optional[str] = None
    password_reset_expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class FarmerProfileRow(BaseModel):
    """Represents a row in the ``farmer_profiles`` table."""

    id: int
    farmer_id: int          # FK → farmers.id

    # Location
    state: Optional[str] = None
    district: Optional[str] = None

    # Farming details
    land_size_acres: Optional[Decimal] = None
    primary_crop: Optional[str] = None
    other_crops: Optional[List[str]] = None
    farming_type: Optional[str] = None

    # Demographics
    age: Optional[int] = None
    gender: Optional[str] = None
    category: Optional[str] = None
    annual_income: Optional[Decimal] = None

    # Eligibility indicators
    has_aadhaar: Optional[bool] = None
    occupation: Optional[str] = None

    # Consent
    consent_given: bool = False
    consent_given_at: Optional[datetime] = None
    consent_version: str = "1.0"

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SavedSchemeRow(BaseModel):
    """Represents a row in the ``saved_schemes`` table."""

    id: int
    farmer_id: int
    scheme_id: str
    scheme_name: str
    notes: Optional[str] = None
    eligibility_status: Optional[str] = None
    saved_at: Optional[datetime] = None


class SearchHistoryRow(BaseModel):
    """Represents a row in the ``search_history`` table."""

    id: int
    farmer_id: int
    query: str
    results_count: int = 0
    language: str = "en"
    searched_at: Optional[datetime] = None


class RefreshTokenRow(BaseModel):
    """Represents a row in the ``refresh_tokens`` table."""

    id: int
    farmer_id: int
    token_hash: str
    expires_at: datetime
    revoked: bool = False
    revoked_at: Optional[datetime] = None
    user_agent: Optional[str] = None
    ip_address: Optional[str] = None
    created_at: Optional[datetime] = None
