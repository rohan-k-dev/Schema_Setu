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
    # Migration 0003 (secure sessions)
    failed_login_count: int = 0
    locked_until: Optional[datetime] = None
    password_changed_at: Optional[datetime] = None
    # Migration 0006 (RBAC): FARMER / REVIEWER / ADMIN — never taken from request input
    role: str = "FARMER"
    # Migration 0008: set only after an SMS code confirmed the number
    phone_verified_at: Optional[datetime] = None
    # Migration 0010: a REVIEWER works cases only once an administrator approved the account
    reviewer_approved_at: Optional[datetime] = None
    reviewer_approved_by: Optional[str] = None


class AuthSessionRow(BaseModel):
    """Represents a row in the ``auth_sessions`` table."""

    id: int
    farmer_id: int            # farmers.id
    session_hash: str
    user_agent_hash: str
    ip_address: Optional[str] = None
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: Optional[datetime] = None
    revoked_reason: Optional[str] = None
    reauthenticated_at: Optional[datetime] = None   # migration 0010: password re-entered in this session


class AuthTokenRow(BaseModel):
    """Represents a row in the ``auth_tokens`` table (e-mail verification / password reset)."""

    id: int
    farmer_id: int            # farmers.id
    purpose: str              # 'verify_email' | 'reset_password'
    token_hash: str
    created_at: datetime
    expires_at: datetime
    used_at: Optional[datetime] = None


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

    # Migration 0004 (profile module)
    land_size_value: Optional[Decimal] = None   # as entered, in land_unit
    land_unit: Optional[str] = None             # acre | hectare | guntha | cent
    income_range: Optional[str] = None
    residence: Optional[str] = None             # rural | urban
    version: int = 1


class SavedSchemeRow(BaseModel):
    """Represents a row in the ``saved_schemes`` table."""

    id: int
    farmer_id: int
    scheme_id: str
    scheme_name: str
    notes: Optional[str] = None
    eligibility_status: Optional[str] = None
    saved_at: Optional[datetime] = None
    # Migration 0005: scheme version the checklist is synced to, and user-reported progress
    scheme_version: Optional[str] = None
    saved_scheme_version: Optional[str] = None
    scheme_data_version: Optional[str] = None
    previous_scheme_version: Optional[str] = None
    scheme_changed_at: Optional[datetime] = None
    scheme_update_seen: bool = True
    application_reference: Optional[str] = None
    application_reference_updated_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AuditEventRow(BaseModel):
    """Represents a row in the append-only ``audit_events`` table (migration 0006)."""

    id: int
    occurred_at: datetime
    actor_account_id: Optional[int] = None
    actor_label: str
    actor_role: Optional[str] = None
    action: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    details: Optional[Any] = None
    ip_address: Optional[str] = None
    # Migration 0007: outcome, correlation id, hash chain
    outcome: str = "SUCCESS"
    correlation_id: Optional[str] = None
    prev_hash: Optional[str] = None
    entry_hash: Optional[str] = None


class ChecklistItemRow(BaseModel):
    """Represents a row in the ``saved_scheme_checklist_items`` table (migration 0005)."""

    id: int
    saved_scheme_id: int
    farmer_id: int
    item_key: str
    category: str
    source: str                       # SCHEME (from the scheme data) / USER (farmer's milestone)
    label: str
    detail: Optional[str] = None
    position: int = 0
    completed: bool = False
    completed_at: Optional[datetime] = None
    note: Optional[str] = None
    introduced_in_version: Optional[str] = None
    removed_in_version: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


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
