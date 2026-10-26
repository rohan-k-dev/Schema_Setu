"""
API response models — Phase 4 typed contracts.

Typed response schemas ensuring consistent API contracts.
Frontend and backend use the same field names.
Supports all Phase 4 response statuses (§48–49).
"""

from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field

from app.core.config import APP_VERSION


class ErrorDetail(BaseModel):
    """Structured error information."""
    code: str
    message: str
    request_id: Optional[str] = None


class SchemeResponse(BaseModel):
    """Structured scheme data in API response (§48, §126)."""
    scheme_id: Optional[str] = None
    name: str = ""
    description: Optional[str] = None
    benefit_summary: Optional[str] = None
    eligibility_summary: Optional[str] = None
    documents: List[str] = Field(default_factory=list)
    application_steps: List[str] = Field(default_factory=list)
    official_url: Optional[str] = None
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    retrieval_sources: List[str] = Field(default_factory=list)
    matched_fields: List[str] = Field(default_factory=list)
    graph_evidence: List[str] = Field(default_factory=list)


class RetrievalMetadataResponse(BaseModel):
    """Retrieval performance metadata (§61)."""
    db_latency_ms: Optional[float] = None
    graph_latency_ms: Optional[float] = None
    web_latency_ms: Optional[float] = None
    total_retrieval_ms: Optional[float] = None
    retrieval_success: Dict[str, bool] = Field(default_factory=dict)
    candidate_count: int = 0
    conflict_count: int = 0


class ChatResponse(BaseModel):
    """
    Response for POST /chat and POST /voice.

    status values (§49):
      - "asking_question": agent is asking a follow-up
      - "schemes_found": scheme search completed
      - "scheme_details": detailed info about a specific scheme
      - "no_results": no matching schemes found
      - "partial_results": some retrieval channels failed
      - "clarification_required": ambiguous query needs clarification
      - "error": something went wrong
    """
    status: str
    reply: Optional[str] = None
    current_profile: Optional[Dict[str, Any]] = None
    schemes: Optional[List[Dict[str, Any]]] = None
    user_transcript: Optional[str] = None
    error: Optional[ErrorDetail] = None
    request_id: Optional[str] = None
    retrieval_metadata: Optional[Dict[str, Any]] = None
    live_check: Optional[Dict[str, Any]] = None       # which official sources were checked now (and which failed)
    recommendation_summary: Optional[Dict[str, Any]] = None   # eligible / alternatives counts (docs/RECOMMENDATIONS.md)
    review: Optional[Dict[str, Any]] = None
    thread_id: Optional[str] = None
    profile_saved: Optional[bool] = None
    profile_save_error: Optional[str] = None


class TTSResponse(BaseModel):
    """Response for POST /tts."""
    audio_base64: Optional[str] = None
    error: Optional[ErrorDetail] = None
    request_id: Optional[str] = None


class HealthResponse(BaseModel):
    """Response for GET /health."""
    status: str
    db_connected: bool = False
    graph_available: bool = False
    environment: Optional[str] = None
    version: str = APP_VERSION


class LivenessResponse(BaseModel):
    """Response for GET /health/live."""
    status: str = "alive"


class ReadinessResponse(BaseModel):
    """Response for GET /health/ready."""
    status: str
    db_ready: bool = False
    graph_ready: bool = False
    groq_configured: bool = False
    tavily_configured: bool = False
    sarvam_configured: bool = False
