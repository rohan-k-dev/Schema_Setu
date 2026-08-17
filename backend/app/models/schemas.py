from pydantic import BaseModel, Field
from typing import Optional, List

class FarmerProfile(BaseModel):
    """
    The data matrix parsed and updated by the LangGraph agent.
    """
    farmer_id: Optional[str] = None
    state: Optional[str] = None
    district: Optional[str] = None
    land_size_acres: Optional[float] = None
    primary_crop: Optional[str] = None
    annual_income: Optional[float] = None
    category: Optional[str] = Field(None, description="General, OBC, SC, ST")
    gender: Optional[str] = None
    has_aadhaar: Optional[bool] = None

class SchemeSchema(BaseModel):
    """
    Schema for local caching/storing of government schemes.
    """
    scheme_id: str
    title: str
    ministry: str
    state_specific: Optional[str] = None  # None if central scheme
    eligibility_criteria_raw: str
    benefits_details: str
    application_link: Optional[str] = None