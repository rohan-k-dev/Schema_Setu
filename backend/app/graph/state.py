"""
LangGraph state definition for the SchemeSetu Agent workflow.

Phase 4: Expanded typed state for the multi-agent architecture.
Uses TypedDict for LangGraph compatibility with proper typing.
Messages use the 'add' reducer to append rather than overwrite.

§10 — State fields.
§11 — State ownership.
"""

from typing import TypedDict, Annotated, List, Optional, Dict, Any
from langchain_core.messages import BaseMessage
from operator import add


class SchemeSetuState(TypedDict):
    """
    Central state object for the SchemeSetu multi-agent LangGraph workflow.

    State ownership:
      - messages: conversation history (append-only via 'add' reducer)
      - profile: canonical user profile (dict for LangGraph serialization)
      - missing_fields: deterministic completeness result
      - profile_complete: whether required fields are present
      - profile_conflicts: detected contradictions in user data
      - original_query: raw user message for the current turn
      - normalized_query: normalized version for search
      - contextual_query: rewritten standalone query with resolved references
      - query_intent: classified intent from query rewriter
      - referenced_scheme_id: specific scheme referenced in follow-up
      - needs_clarification: whether query is ambiguous
      - graph_candidates: Knowledge Graph retrieval output
      - db_candidates: PostgreSQL retrieval output
      - web_candidates: Tavily retrieval output
      - merged_candidates: normalized combined results
      - retrieval_errors: per-source failure information
      - source_conflicts: detected conflicting facts across sources
      - graph_evidence: graph relationship evidence
      - response_text: final user-facing response text
      - response_status: typed response status
      - response_schemes: structured scheme data for API response
      - retrieval_metadata: performance + availability metadata
      - native_language: detected language for future multilingual support
      - session_id: unique session identifier
      - error: error message if processing failed
    """

    # ─── Conversation ────────────────────────────────────────
    # 'add' operator ensures messages are appended, never overwritten
    messages: Annotated[List[BaseMessage], add]

    # ─── Profile ─────────────────────────────────────────────
    profile: Optional[Dict[str, Any]]
    missing_fields: List[str]
    profile_complete: bool
    profile_conflicts: List[Dict[str, Any]]

    # ─── Query Context ───────────────────────────────────────
    original_query: Optional[str]
    normalized_query: Optional[str]
    contextual_query: Optional[str]
    query_intent: Optional[str]
    referenced_scheme_id: Optional[str]
    needs_clarification: bool

    # ─── Retrieval Results ───────────────────────────────────
    graph_candidates: List[Dict[str, Any]]
    db_candidates: List[Dict[str, Any]]
    web_candidates: List[Dict[str, Any]]
    merged_candidates: List[Dict[str, Any]]

    # ─── Retrieval Metadata ──────────────────────────────────
    retrieval_errors: Dict[str, str]
    source_conflicts: List[Dict[str, Any]]
    graph_evidence: List[Dict[str, Any]]
    retrieval_metadata: Optional[Dict[str, Any]]
    live_check: Optional[Dict[str, Any]]        # query-time official-source check (docs/LIVE_VERIFICATION.md)

    # ─── Eligibility (Phase 5) ───────────────────────────────
    eligibility_results: List[Any]
    recommendation_results: List[Any]
    recommendation_sections: Optional[Dict[str, Any]]   # eligible / alternatives (docs/RECOMMENDATIONS.md)
    missing_eligibility_fields: List[str]
    eligibility_errors: List[str]

    # ─── Response ────────────────────────────────────────────
    response_text: Optional[str]
    response_status: Optional[str]
    response_schemes: List[Dict[str, Any]]

    # ─── Session & Language (Phase 6, §10) ──────────────────
    language: Optional[str]           # Internal code e.g. "hi", "kn"
    language_name: Optional[str]      # Display name e.g. "हिन्दी"
    language_mode: Optional[str]      # "manual" or "auto"
    native_language: Optional[str]    # Legacy / ASR-detected language
    session_id: Optional[str]
    error: Optional[str]

    # ─── Human Review (Phase 6, §56) ─────────────────────────
    needs_review: bool
    review_reason: Optional[str]
    review_case_id: Optional[str]


# Backward compatibility alias
KisanState = SchemeSetuState