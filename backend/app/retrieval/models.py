"""
Retrieval data models for Phase 4.

Typed contracts for retrieval requests, results, merged candidates,
source conflicts, and response status. Used across all retrieval
components and agents.

§28, §66, §48, §76 of Phase 4 spec.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field


# ─── Source Types ─────────────────────────────────────────────

class SourceType(str, enum.Enum):
    """Origin of a retrieval result."""
    DATABASE = "DATABASE"
    KNOWLEDGE_GRAPH = "KNOWLEDGE_GRAPH"
    LIVE_WEB = "LIVE_WEB"


class SourceTrust(str, enum.Enum):
    """Trust level for a source (Phase 1 taxonomy §224)."""
    OFFICIAL = "OFFICIAL"
    SECONDARY = "SECONDARY"
    UNKNOWN = "UNKNOWN"


# ─── Query Intent ─────────────────────────────────────────────

class QueryIntent(str, enum.Enum):
    """Classified intent from the query rewriter (§23)."""
    SCHEME_SEARCH = "scheme_search"
    SCHEME_DETAILS = "scheme_details"
    APPLICATION_STEPS = "application_steps"
    DOCUMENTS = "documents"
    BENEFITS = "benefits"
    ELIGIBILITY_INFORMATION = "eligibility_information"
    GENERAL_FOLLOWUP = "general_followup"
    PROFILE_UPDATE = "profile_update"
    UNKNOWN = "unknown"


# ─── Response Status ──────────────────────────────────────────

class ResponseStatus(str, enum.Enum):
    """All possible response statuses (§49)."""
    ASKING_QUESTION = "asking_question"
    SCHEMES_FOUND = "schemes_found"
    SCHEME_DETAILS = "scheme_details"
    NO_RESULTS = "no_results"
    PARTIAL_RESULTS = "partial_results"
    ERROR = "error"
    CLARIFICATION_REQUIRED = "clarification_required"


# ─── Retrieval Request ────────────────────────────────────────

class RetrievalRequest(BaseModel):
    """
    Typed retrieval request constructed from profile + query context (§66).
    Shared across DB, Graph, and Web retrievers.
    """
    query: str = ""
    contextual_query: str = ""
    state: Optional[str] = None
    district: Optional[str] = None
    crop: Optional[str] = None
    category: Optional[str] = None
    gender: Optional[str] = None
    occupation: Optional[str] = None
    intent: QueryIntent = QueryIntent.SCHEME_SEARCH
    referenced_scheme_id: Optional[str] = None


# ─── Retrieval Result ─────────────────────────────────────────

class RetrievalResult(BaseModel):
    """
    A single result from one retrieval source (§28).
    All retrievers normalize into this shape.
    """
    source_type: SourceType
    source_id: Optional[str] = None
    scheme_id: Optional[str] = None
    title: str = ""
    description: Optional[str] = None
    benefits: Optional[str] = None
    eligibility_summary: Optional[str] = None
    documents: Optional[List[str]] = None
    application_steps: Optional[List[str]] = None
    official_url: Optional[str] = None
    source_url: Optional[str] = None
    source_name: Optional[str] = None
    source_trust: SourceTrust = SourceTrust.UNKNOWN
    retrieved_at: Optional[str] = None
    evidence: Optional[Dict[str, Any]] = None
    raw_reference: Optional[Dict[str, Any]] = None


# ─── Source Record ────────────────────────────────────────────

class SourceRecord(BaseModel):
    """Source provenance for a merged candidate (§42)."""
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    source_type: SourceType = SourceType.DATABASE
    source_trust: SourceTrust = SourceTrust.UNKNOWN


# ─── Source Conflict ──────────────────────────────────────────

class SourceConflict(BaseModel):
    """Detected conflict between sources for the same scheme field (§76)."""
    scheme_id: str
    field: str
    values: Dict[str, Any] = Field(default_factory=dict)
    sources: List[str] = Field(default_factory=list)


# ─── Merged Candidate ────────────────────────────────────────

class MergedCandidate(BaseModel):
    """
    A scheme candidate after merge/dedup across all sources (§39, §122).
    Carries combined evidence and provenance.
    """
    candidate_id: str = ""
    scheme_id: str = ""
    name: str = ""
    description: Optional[str] = None
    benefit_summary: Optional[str] = None
    eligibility_summary: Optional[str] = None
    documents: Optional[List[str]] = None
    application_steps: Optional[List[str]] = None
    official_url: Optional[str] = None
    retrieval_sources: List[SourceType] = Field(default_factory=list)
    matched_fields: List[str] = Field(default_factory=list)
    graph_evidence: Optional[List[str]] = None
    source_records: List[SourceRecord] = Field(default_factory=list)
    source_conflicts: List[SourceConflict] = Field(default_factory=list)

    def to_response_dict(self) -> Dict[str, Any]:
        """Convert to API-safe dictionary for response formatting."""
        return {
            "scheme_id": self.scheme_id,
            "name": self.name,
            "description": self.description,
            "benefit_summary": self.benefit_summary,
            "eligibility_summary": self.eligibility_summary,
            "documents": self.documents or [],
            "application_steps": self.application_steps or [],
            "official_url": self.official_url,
            "sources": [
                {"name": s.source_name, "url": s.source_url, "type": s.source_type.value}
                for s in self.source_records if s.source_name
            ],
            "retrieval_sources": [s.value for s in self.retrieval_sources],
            "matched_fields": self.matched_fields,
            "graph_evidence": self.graph_evidence or [],
        }


# ─── Query Rewrite Output ────────────────────────────────────

class QueryRewriteResult(BaseModel):
    """Structured output from the query rewriter (§23)."""
    standalone_query: str = ""
    intent: QueryIntent = QueryIntent.SCHEME_SEARCH
    referenced_scheme_id: Optional[str] = None
    needs_clarification: bool = False
    clarification_reason: Optional[str] = None


# ─── Profile Conflict ────────────────────────────────────────

class ProfileConflict(BaseModel):
    """Detected contradiction in user-supplied profile data (§15)."""
    field: str
    old_value: Any = None
    new_value: Any = None


# ─── Retrieval Metadata ──────────────────────────────────────

class RetrievalMetadata(BaseModel):
    """Performance and availability metadata for a retrieval run (§61)."""
    db_latency_ms: Optional[float] = None
    graph_latency_ms: Optional[float] = None
    web_latency_ms: Optional[float] = None
    total_retrieval_ms: Optional[float] = None
    retrieval_success: Dict[str, bool] = Field(default_factory=dict)
    candidate_count: int = 0
    conflict_count: int = 0
