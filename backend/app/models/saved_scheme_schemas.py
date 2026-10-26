"""
Saved schemes and application checklists — request / response models
(docs/SAVED_SCHEMES.md).

Progress is USER-REPORTED: SchemeSetu is not connected to any government
application-tracking system, so nothing here means a department has confirmed a step.
"""

from __future__ import annotations

import re
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, StrictBool, field_validator, model_validator

ChecklistCategory = Literal["DOCUMENT", "PREPARATION", "APPLICATION", "SUBMISSION",
                            "ACKNOWLEDGEMENT", "MILESTONE"]
Stage = Literal["NOT_STARTED", "PREPARING", "SUBMITTED", "ACKNOWLEDGED"]

PROGRESS_NOTICE = ("Progress is recorded by you. SchemeSetu is not connected to any government "
                   "application-tracking system, so no department has confirmed these steps.")

_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 /._\-]{0,63}$")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(v: Optional[str], *, multiline: bool) -> Optional[str]:
    """Trim; reject blank text (send null to clear) and control characters."""
    if v is None:
        return None
    s = v.strip() if multiline else " ".join(v.split())
    if not s:
        raise ValueError("must not be blank (send null to clear it)")
    if _CONTROL.search(s):
        raise ValueError("contains characters that are not allowed")
    return s


# ─── Requests ─────────────────────────────────────────────────────────────────

class SavedSchemeUpdateRequest(BaseModel):
    """
    PATCH /farmers/me/saved-schemes/{scheme_id}. Fields left out are unchanged;
    null clears notes / the application reference.
    """

    model_config = {"extra": "forbid"}

    notes: Optional[str] = Field(default=None, max_length=1000)
    # Only if the farmer chooses to record it (receipt / SMS / portal number).
    application_reference: Optional[str] = Field(default=None, max_length=64)
    # true = "I've seen that the scheme's information changed" (hides the notice)
    acknowledge_scheme_update: Optional[Literal[True]] = None

    @field_validator("notes")
    @classmethod
    def _v_notes(cls, v):
        return clean_text(v, multiline=True)

    @field_validator("application_reference")
    @classmethod
    def _v_reference(cls, v):
        if v is None:
            return None
        v = v.strip()                       # not collapsed: a line break inside is rejected, not rewritten
        if not _REFERENCE.match(v):
            raise ValueError("use letters, numbers, spaces and / . _ - only (up to 64 characters)")
        return v

    @model_validator(mode="after")
    def _v_not_empty(self):
        if not self.model_fields_set:
            raise ValueError("nothing to update")
        return self


class ChecklistItemUpdateRequest(BaseModel):
    """PATCH …/checklist/{item_id}: mark complete / incomplete and/or set the note (null clears)."""

    model_config = {"extra": "forbid"}

    completed: Optional[StrictBool] = None              # "yes" / 1 are rejected, not coerced
    note: Optional[str] = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def _v_note(cls, v):
        return clean_text(v, multiline=True)

    @model_validator(mode="after")
    def _v_fields(self):
        if not self.model_fields_set:
            raise ValueError("nothing to update")
        if "completed" in self.model_fields_set and self.completed is None:
            raise ValueError("completed must be true or false")
        return self


class MilestoneCreateRequest(BaseModel):
    """POST …/checklist: the farmer's own milestone, e.g. "Field verification done"."""

    model_config = {"extra": "forbid"}

    label: str = Field(min_length=1, max_length=120)
    note: Optional[str] = Field(default=None, max_length=500)
    completed: StrictBool = False

    @field_validator("label")
    @classmethod
    def _v_label(cls, v):
        return clean_text(v, multiline=False)

    @field_validator("note")
    @classmethod
    def _v_note(cls, v):
        return clean_text(v, multiline=True)


# ─── Responses ────────────────────────────────────────────────────────────────

class ChecklistItem(BaseModel):
    id: int
    key: str
    category: ChecklistCategory
    source: Literal["SCHEME", "USER"]       # from the scheme data / the farmer's own milestone
    label: str
    detail: Optional[str]
    completed: bool
    completed_at: Optional[str]
    note: Optional[str]
    # False: a scheme update no longer lists this item (kept so your record isn't lost;
    # not counted in progress).
    current: bool
    added_in_update: bool                   # added by the latest scheme update


class ProgressSummary(BaseModel):
    completed: int
    total: int                              # current items only
    stage: Stage                            # derived from the farmer's own ticks
    reported_by: Literal["FARMER"] = "FARMER"


class SchemeUpdateNotice(BaseModel):
    """The scheme's information changed after you saved it (until acknowledged)."""

    changed_at: Optional[str]
    previous_version: Optional[str]
    current_version: str
    added: List[str]
    removed: List[str]


class SavedSchemeSummary(BaseModel):
    id: int
    scheme_id: str
    scheme_name: str
    eligibility_status: Optional[str]
    notes: Optional[str]
    saved_at: Optional[str]
    application_reference: Optional[str]
    scheme_available: bool                  # False: no longer in SchemeSetu's database
    scheme_status: Optional[str]            # ACTIVE / INACTIVE / … (None if unavailable)
    scheme_version: Optional[str]           # short content hash the checklist is synced to
    saved_scheme_version: Optional[str]     # … and the one it was first saved with
    scheme_data_version: Optional[str]
    official_url: Optional[str]
    application_url: Optional[str]
    progress: ProgressSummary
    update_notice: Optional[SchemeUpdateNotice]
    progress_source: Literal["USER_REPORTED"] = "USER_REPORTED"
    official_tracking: Literal[False] = False


class SavedSchemeDetail(SavedSchemeSummary):
    checklist: List[ChecklistItem]
    progress_notice: str = PROGRESS_NOTICE


class SaveSchemeResult(SavedSchemeDetail):
    created: bool                           # False: it was already saved (nothing changed)
