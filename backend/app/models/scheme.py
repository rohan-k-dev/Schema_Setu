"""
Scheme data model.

Represents a government scheme record from the database or web search.
Designed to be extensible for future phases without breaking the API.
"""

from typing import Optional
from pydantic import BaseModel


class Scheme(BaseModel):
    """A government scheme record."""
    scheme_id: Optional[str] = None
    title: str
    ministry: Optional[str] = None
    state_specific: Optional[str] = None
    eligibility_criteria_raw: Optional[str] = None
    benefits_details: Optional[str] = None
    application_link: Optional[str] = None
    source: Optional[str] = None
    source_url: Optional[str] = None

    model_config = {"extra": "ignore"}


class RecommendedScheme(BaseModel):
    """A scheme recommendation with XAI explanation."""
    scheme_name: str
    benefit: str
    xai_explanation: str
    source: Optional[str] = None

    model_config = {"extra": "ignore"}
