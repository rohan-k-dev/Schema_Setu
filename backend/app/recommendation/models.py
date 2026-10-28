"""
Recommendation models — Phase 5.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from app.eligibility.models import EligibilityStatus


class RankedScheme(BaseModel):
    """A scheme with its ranking information."""
    scheme_id: str
    scheme_name: str = ""
    eligibility_status: EligibilityStatus
    profile_match_score: float = 0.0
    rank: int = 0
    rank_reasons: List[str] = Field(default_factory=list)
    eligibility_result: Optional[Dict[str, Any]] = None
    explanation: Optional[str] = None
