"""
Pydantic schemas for the farmer authentication and profile API.

These are the contract between the HTTP layer and the service layer.
They are SEPARATE from the DB domain models in app.models.db.farmer_auth.
"""

from __future__ import annotations

from typing import Annotated, Any, List, Literal, Optional
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


# ─── Registration ─────────────────────────────────────────────────────────────

def _password_strength(v: str) -> str:
    if not any(c.isdigit() for c in v):
        raise ValueError("Password must contain at least one digit.")
    if not any(c.isalpha() for c in v):
        raise ValueError("Password must contain at least one letter.")
    if not v.strip():
        raise ValueError("Password cannot be only spaces.")
    return v


# Opaque tokens are 43 URL-safe characters; the bound only rejects junk early.
TokenStr = Field(min_length=20, max_length=200)


class RegisterRequest(BaseModel):
    """Payload for POST /auth/register. Unexpected fields (e.g. ``role``) are rejected: every
    new account is a FARMER (docs/RBAC.md)."""

    model_config = {"extra": "forbid"}

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=20)

    @field_validator("password")
    @classmethod
    def _v_password_strength(cls, v: str) -> str:
        return _password_strength(v)


# ─── Login / session ──────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    """Payload for POST /auth/login."""

    email: EmailStr
    # Bounded so a huge body cannot be fed to the (deliberately slow) password hash.
    password: str = Field(min_length=1, max_length=128)


class AuthUser(BaseModel):
    """The signed-in account (no sensitive fields)."""

    farmer_id: str
    email: str
    full_name: Optional[str] = None
    is_verified: bool
    # For display only (e.g. showing a Review link); every permission is checked on the server.
    role: str = "FARMER"


class SessionResponse(BaseModel):
    """Returned by POST /auth/login and GET /auth/session.

    The session itself travels only in the HttpOnly cookie; csrf_token must be
    sent back in the X-CSRF-Token header on state-changing requests.
    """

    user: AuthUser
    csrf_token: str
    session_expires_at: str           # ISO timestamp (absolute expiry)


class MessageResponse(BaseModel):
    message: str


class EmailOnlyRequest(BaseModel):
    """Payload for POST /auth/forgot-password."""

    email: EmailStr


# ─── Password reset / change ──────────────────────────────────────────────────

ForgotPasswordRequest = EmailOnlyRequest


class ResetPasswordRequest(BaseModel):
    """Payload for POST /auth/reset-password."""

    token: str = TokenStr
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _v_password_strength(cls, v: str) -> str:
        return _password_strength(v)


class ReauthRequest(BaseModel):
    """Payload for POST /auth/reauthenticate: confirm the password before a sensitive action."""

    model_config = {"extra": "forbid"}
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    """Payload for POST /auth/change-password (signed in)."""

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _v_password_strength(cls, v: str) -> str:
        return _password_strength(v)


# ─── Profile ──────────────────────────────────────────────────────────────────

LandUnit = Literal["acre", "hectare", "guntha", "cent"]
IncomeRange = Literal["below_1_lakh", "1_to_2.5_lakh", "2.5_to_5_lakh", "5_to_10_lakh", "above_10_lakh"]
Residence = Literal["rural", "urban"]
FarmingType = Literal["subsistence", "commercial", "mixed"]
ShortText = Annotated[str, Field(min_length=1, max_length=60)]


class ProfileUpdateRequest(BaseModel):
    """
    Payload for PUT /farmers/me/profile — a partial update.

    - A field that is **left out** keeps its saved value.
    - A field sent as **null** is cleared to UNKNOWN (e.g. "I'm not sure any more").
    - Unknown is never turned into "no"/false; there are no yes/no defaults.

    Only fields the eligibility engine uses (plus optional crop details) are accepted.
    Unexpected fields — e.g. an Aadhaar number or another farmer's id — are rejected (422).
    Aadhaar status and exact income are not collected: no eligibility rule uses them.
    """

    model_config = {"extra": "forbid"}

    state: Optional[str] = Field(default=None, max_length=60)
    district: Optional[str] = Field(default=None, max_length=100)
    land_size: Optional[float] = Field(default=None, ge=0, le=100_000)
    land_unit: Optional[LandUnit] = None
    primary_crop: Optional[str] = Field(default=None, max_length=60)
    other_crops: Optional[List[ShortText]] = Field(default=None, max_length=10)
    farming_type: Optional[FarmingType] = None
    occupation: Optional[str] = Field(default=None, max_length=60)
    age: Optional[int] = Field(default=None, ge=1, le=119)
    gender: Optional[str] = None
    category: Optional[str] = None
    income_range: Optional[IncomeRange] = None
    residence: Optional[Residence] = None
    # Consent MUST be explicitly given before personal data is first saved
    consent_given: bool = False
    # The version the client loaded; a stale version is rejected with 409 (conflicting edit)
    expected_version: Optional[int] = Field(default=None, ge=0)

    @field_validator("state")
    @classmethod
    def _v_state(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        from app.models.profile import canonical_state
        canon = canonical_state(v)
        if canon is None:
            raise ValueError(f"'{v}' is not an Indian state or union territory")
        return canon

    @field_validator("district", "occupation", "primary_crop")
    @classmethod
    def _v_text(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = " ".join(v.split())
        if not s:
            raise ValueError("must not be blank (send null to clear it)")
        if any(ch in s for ch in "<>{}[]\\;"):
            raise ValueError("contains characters that are not allowed")
        return s

    @field_validator("gender")
    @classmethod
    def _v_gender(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        from app.models.profile import _GENDER_CANONICAL
        canon = _GENDER_CANONICAL.get(v.strip().lower())
        if canon is None:
            raise ValueError("gender must be male, female or other (or null if not given)")
        return canon

    @field_validator("category")
    @classmethod
    def _v_category(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        from app.models.profile import _CATEGORY_CANONICAL
        canon = _CATEGORY_CANONICAL.get(" ".join(v.split()).lower())
        if canon is None:
            raise ValueError("category must be one of General, OBC, SC, ST, EWS (or null)")
        return canon

    @model_validator(mode="after")
    def _v_land_pair(self) -> "ProfileUpdateRequest":
        sent = self.model_fields_set
        if self.land_size is not None and self.land_unit is None:
            raise ValueError("land_unit is required when land_size is given")
        if "land_unit" in sent and self.land_unit is not None and "land_size" not in sent:
            raise ValueError("send land_size together with land_unit")
        return self


class ProfileResponse(BaseModel):
    """Farmer profile returned from GET /farmers/me/profile. null = unknown / not given."""

    farmer_id: str
    full_name: Optional[str]
    email: str
    state: Optional[str]
    district: Optional[str]
    land_size: Optional[float]            # as entered, in land_unit
    land_unit: Optional[str]
    land_size_acres: Optional[float]      # converted; what the eligibility engine uses
    primary_crop: Optional[str]
    other_crops: Optional[List[str]]
    farming_type: Optional[str]
    occupation: Optional[str]
    age: Optional[int]
    gender: Optional[str]
    category: Optional[str]
    income_range: Optional[str]
    residence: Optional[str]
    consent_given: bool
    consent_given_at: Optional[str]   # ISO timestamp string
    profile_completeness: float       # 0–100 %
    version: int                      # send back as expected_version when saving
    updated_at: Optional[str]         # ISO timestamp


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
    """
    Payload for POST /farmers/me/saved-schemes.

    Only schemes in SchemeSetu's database can be saved; the name and version are taken
    from the database, so ``scheme_name`` is accepted for compatibility but not trusted.
    """

    model_config = {"extra": "forbid"}

    scheme_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_\-]+$")
    scheme_name: Optional[str] = Field(default=None, max_length=500)
    # Status shown when it was saved; the dashboard flags it when it changes later.
    eligibility_status: Optional[Literal["ELIGIBLE", "NOT_ELIGIBLE", "NEEDS_MORE_INFORMATION",
                                         "UNVERIFIABLE"]] = None
    notes: Optional[str] = Field(default=None, max_length=1000)


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
