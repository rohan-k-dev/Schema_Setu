"""
Human Review Models — Phase 6 (§58–§65).

Data models for the human-in-the-loop escalation workflow.
Cases are created when the automated system detects ambiguous
or unverifiable situations that need human judgment.

IMPORTANT: Review cases must NOT contain Aadhaar numbers,
bank information, or unnecessary identity data (§61).
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class ReviewStatus(str, Enum):
    """Review case lifecycle states (§59)."""
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class ReviewReason(str, Enum):
    """Controlled escalation reason values (§60)."""
    UNVERIFIABLE = "UNVERIFIABLE"
    RULE_CONFLICT = "RULE_CONFLICT"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    SYSTEM_ERROR = "SYSTEM_ERROR"
    AMBIGUOUS_QUERY = "AMBIGUOUS_QUERY"
    OTHER = "OTHER"


class ReviewAction(str, Enum):
    """Reviewer action types (§63)."""
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_INFORMATION = "REQUEST_INFORMATION"
    MARK_UNVERIFIABLE = "MARK_UNVERIFIABLE"


# Valid status transitions (§125)
VALID_TRANSITIONS: Dict[ReviewStatus, List[ReviewStatus]] = {
    ReviewStatus.PENDING: [ReviewStatus.IN_REVIEW, ReviewStatus.DISMISSED],
    ReviewStatus.IN_REVIEW: [ReviewStatus.RESOLVED, ReviewStatus.DISMISSED],
    ReviewStatus.RESOLVED: [],  # Terminal
    ReviewStatus.DISMISSED: [],  # Terminal
}

# Fields to strip from profile snapshots (§61)
SENSITIVE_FIELDS = {"aadhaar_number", "bank_account", "pan_number", "phone_number",
                    "farmer_id", "name", "email", "address"}


@dataclass
class ReviewCase:
    """
    A human review case (§58).

    Created automatically when the system detects situations
    that cannot be reliably resolved by the automated pipeline.
    """
    case_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    session_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    status: ReviewStatus = ReviewStatus.PENDING
    reason: ReviewReason = ReviewReason.OTHER
    query: str = ""
    profile_snapshot: Dict[str, Any] = field(default_factory=dict)
    scheme_ids: List[str] = field(default_factory=list)
    eligibility_results: List[Dict[str, Any]] = field(default_factory=list)
    source_conflicts: List[Dict[str, Any]] = field(default_factory=list)
    created_by_system: bool = True
    # Reviewer fields
    reviewer_id: Optional[str] = None
    reviewer_note: Optional[str] = None
    reviewer_action: Optional[str] = None
    reviewed_at: Optional[str] = None

    def sanitize_profile(self) -> None:
        """Strip sensitive fields from profile snapshot (§61)."""
        for field_name in SENSITIVE_FIELDS:
            self.profile_snapshot.pop(field_name, None)


@dataclass
class ReviewAuditEntry:
    """Audit log entry for review actions (§70, §126)."""
    case_id: str
    action: str
    reviewer: str = "system"
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    note: str = ""


def is_valid_transition(current: ReviewStatus, target: ReviewStatus) -> bool:
    """Check if a status transition is allowed (§125)."""
    return target in VALID_TRANSITIONS.get(current, [])
