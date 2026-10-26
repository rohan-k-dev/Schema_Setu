"""
Request / response models for administration, scheme curation and the audit log
(docs/RBAC.md). Account administration shows account metadata only — never
profiles, saved schemes, search history or phone numbers.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, StrictBool, field_validator, model_validator

from app.core.permissions import Role
from app.models.saved_scheme_schemas import clean_text


class MyAccess(BaseModel):
    """GET /auth/permissions — for showing the right links; every check is on the server."""

    role: str
    permissions: List[str]


class AdminUser(BaseModel):
    farmer_id: str
    email: str
    full_name: Optional[str]
    role: str
    is_active: bool
    is_verified: bool
    locked: bool
    reviewer_approved: bool = False
    created_at: Optional[str]
    last_login_at: Optional[str]


class AdminUserPage(BaseModel):
    items: List[AdminUser]
    total: int
    limit: int
    offset: int


class RoleChangeRequest(BaseModel):
    model_config = {"extra": "forbid"}

    role: Role
    # The role the administrator saw; if it changed meanwhile the request gets 409.
    expected_role: Optional[Role] = None


class StatusChangeRequest(BaseModel):
    model_config = {"extra": "forbid"}

    is_active: StrictBool


class SchemeCurationRequest(BaseModel):
    """
    Curation flags only. Rules, documents and other scheme content change through the
    corpus curation / import process, never through the API (phase 6 §64).
    """

    model_config = {"extra": "forbid"}

    status: Optional[Literal["ACTIVE", "INACTIVE", "SUSPENDED"]] = None
    needs_review: Optional[StrictBool] = None
    review_notes: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("review_notes")
    @classmethod
    def _v_notes(cls, v):
        return clean_text(v, multiline=True)

    @model_validator(mode="after")
    def _v_fields(self):
        if not self.model_fields_set:
            raise ValueError("nothing to update")
        for f in ("status", "needs_review"):
            if f in self.model_fields_set and getattr(self, f) is None:
                raise ValueError(f"{f} cannot be null")
        return self


class SchemeCuration(BaseModel):
    scheme_id: str
    name: str
    status: str
    needs_review: bool
    review_notes: Optional[str]
    note: str = ("A corpus re-import restores the corpus values; make lasting corrections "
                 "in the corpus (data curation process).")


class AuditEvent(BaseModel):
    id: int
    occurred_at: str
    actor_label: str
    actor_role: Optional[str]
    action: str
    target_type: Optional[str]
    target_id: Optional[str]
    details: Optional[Dict[str, Any]]
    ip_address: Optional[str]
    outcome: str = "SUCCESS"                 # SUCCESS / FAILURE / DENIED
    correlation_id: Optional[str] = None     # the request's X-Request-ID
    entry_hash: Optional[str] = None


class AuditPage(BaseModel):
    items: List[AuditEvent]
    total: int
    limit: int
    offset: int


class AuditIntegrity(BaseModel):
    """GET /admin/audit-events/verify — the whole hash chain recomputed."""

    valid: bool
    checked: int
    first_broken_id: Optional[int]
    reason: Optional[str]
    verified_at: str


class ReviewerApprovalRequest(BaseModel):
    model_config = {"extra": "forbid"}
    approved: bool
