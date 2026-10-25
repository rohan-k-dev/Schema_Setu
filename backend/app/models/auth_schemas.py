"""
Pydantic schemas for the farmer authentication and profile API.

These are the contract between the HTTP layer and the service layer.
They are SEPARATE from the DB domain models in app.models.db.farmer_auth.
"""

from __future__ import annotations

from typing import Any, List, Optional
from pydantic import BaseModel, EmailStr, Field, field_validator


# ─── Registration ─────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    """Payload for POST /auth/register."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=20)

    @field_validator("password")
    @classmethod
    def _v_password_strength(cls, v: str) -> str:
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit.")
        if not any(c.isalpha() for c in v):
            raise ValueError("Password must contain at least one letter.")
        return v


# ─── Login / Token ────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    """Payload for POST /auth/login."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Returned after successful login or token refresh."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int           # seconds until access token expires
    farmer_id: str


class RefreshRequest(BaseModel):
    """Payload for POST /auth/refresh."""

    refresh_token: str


# ─── Password reset ───────────────────────────────────────────────────────────

class ForgotPasswordRequest(BaseModel):
    """Payload for POST /auth/forgot-password."""

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Payload for POST /auth/reset-password."""

    token: str
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _v_password_strength(cls, v: str) -> str:
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit.")
        if not any(c.isalpha() for c in v):
            raise ValueError("Password must contain at least one letter.")
        return v


# ─── Profile ──────────────────────────────────────────────────────────────────

class ProfileUpdateRequest(BaseModel):
    """Payload for PUT /farmers/me/profile (partial update)."""

    state: Optional[str] = None
    district: Optional[str] = None
    land_size_acres: Optional[float] = Field(default=None, ge=0)
    primary_crop: Optional[str] = None
    other_crops: Optional[List[str]] = None
    farming_type: Optional[str] = None
    age: Optional[int] = Field(default=None, ge=1, le=119)
    gender: Optional[str] = None
    category: Optional[str] = None
    annual_income: Optional[float] = Field(default=None, ge=0)
    has_aadhaar: Optional[bool] = None
    occupation: Optional[str] = None
    # Consent MUST be explicitly given before saving personal data
    consent_given: bool = False

    @field_validator("gender")
    @classmethod
    def _v_gender(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v.lower() not in ("male", "female", "other"):
            raise ValueError("gender must be male, female, or other")
        return v.lower() if v else v

    @field_validator("category")
    @classmethod
    def _v_category(cls, v: Optional[str]) -> Optional[str]:
        allowed = {"General", "OBC", "SC", "ST", "EWS"}
        if v is not None and v not in allowed:
            raise ValueError(f"category must be one of {allowed}")
        return v


class ProfileResponse(BaseModel):
    """Farmer profile returned from GET /farmers/me/profile."""

    farmer_id: str
    full_name: Optional[str]
    email: str
    state: Optional[str]
    district: Optional[str]
    land_size_acres: Optional[float]
    primary_crop: Optional[str]
    other_crops: Optional[List[str]]
    farming_type: Optional[str]
    age: Optional[int]
    gender: Optional[str]
    category: Optional[str]
    annual_income: Optional[float]
    has_aadhaar: Optional[bool]
    occupation: Optional[str]
    consent_given: bool
    consent_given_at: Optional[str]   # ISO timestamp string
    profile_completeness: float       # 0–100 %


# ─── Account info ─────────────────────────────────────────────────────────────

class AccountResponse(BaseModel):
    """Slim account info (no sensitive fields)."""

    farmer_id: str
    email: str
    full_name: Optional[str]
    phone: Optional[str]
    is_active: bool
    is_verified: bool
    created_at: Optional[str]         # ISO timestamp
    last_login_at: Optional[str]      # ISO timestamp


# ─── Saved schemes ────────────────────────────────────────────────────────────

class SaveSchemeRequest(BaseModel):
    """Payload for POST /farmers/me/saved-schemes."""

    scheme_id: str
    scheme_name: str
    eligibility_status: Optional[str] = None
    notes: Optional[str] = None


class SavedSchemeResponse(BaseModel):
    """Single saved scheme entry."""

    id: int
    scheme_id: str
    scheme_name: str
    eligibility_status: Optional[str]
    notes: Optional[str]
    saved_at: Optional[str]           # ISO timestamp


# ─── Search history ───────────────────────────────────────────────────────────

class SearchHistoryEntry(BaseModel):
    """Single search history record."""

    id: int
    query: str
    results_count: int
    language: str
    searched_at: Optional[str]        # ISO timestamp


# ─── Dashboard ───────────────────────────────────────────────────────────────

class DashboardResponse(BaseModel):
    """Aggregated data for the personalized farmer dashboard."""

    account: AccountResponse
    profile: Optional[ProfileResponse]
    missing_fields: List[str]
    profile_completeness: float
    saved_schemes: List[SavedSchemeResponse]
    recent_searches: List[SearchHistoryEntry]
