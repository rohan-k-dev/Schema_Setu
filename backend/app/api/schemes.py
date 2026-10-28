"""
Scheme API routes — Phase 2.

Provides scheme search and detail endpoints backed by PostgreSQL.
Falls back to corpus loader when DB is unavailable.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.database.connection import is_db_available
from app.database.repositories.scheme_repository import SchemeRepository
from app.ingestion.corpus_loader import get_corpus_loader
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["schemes"])


@router.get("/schemes")
async def list_schemes(
    state: Optional[str] = Query(None, description="Filter by state"),
    crop: Optional[str] = Query(None, description="Filter by crop"),
    query: Optional[str] = Query(None, description="Search by name/alias"),
    limit: int = Query(20, ge=1, le=100),
):
    """Search schemes — uses DB if available, else falls back to corpus loader."""
    if is_db_available():
        return await _search_db(state, crop, query, limit)
    else:
        return _search_corpus(state, crop, query, limit)


@router.get("/schemes/{scheme_id}")
async def get_scheme(scheme_id: str):
    """Get a single scheme by its stable ID, with full details if DB available."""
    if is_db_available():
        detail = await SchemeRepository.get_with_details(scheme_id)
        if not detail:
            raise HTTPException(status_code=404, detail=f"Scheme not found: {scheme_id}")
        return _detail_to_response(detail)
    else:
        loader = get_corpus_loader()
        scheme = loader.get_by_id(scheme_id)
        if not scheme:
            raise HTTPException(status_code=404, detail=f"Scheme not found: {scheme_id}")
        return scheme.model_dump(mode="json")


async def _search_db(state, crop, query, limit):
    """Search using PostgreSQL repository."""
    if query:
        # Search by name first, then alias
        results = await SchemeRepository.search_by_name(query)
        if not results:
            results = await SchemeRepository.search_by_alias(query)
    elif state and crop:
        results = await SchemeRepository.search_by_state_and_crop(state, crop)
    elif state:
        results = await SchemeRepository.search_by_state(state)
    elif crop:
        results = await SchemeRepository.search_by_crop(crop)
    else:
        results = await SchemeRepository.list_active()

    schemes = [
        {
            "scheme_id": s.scheme_id,
            "name": s.name,
            "short_name": s.short_name,
            "ministry": s.ministry,
            "level": s.level,
            "status": s.status,
            "description": s.description[:200] + "..." if len(s.description) > 200 else s.description,
            "official_url": s.official_url,
        }
        for s in results[:limit]
    ]
    return {"total": len(results), "schemes": schemes}


def _search_corpus(state, crop, query, limit):
    """Fallback search using in-memory corpus loader."""
    loader = get_corpus_loader()
    results = loader.search(state=state, crop=crop, query=query)
    return {
        "total": len(results),
        "schemes": loader.to_dicts(results[:limit]),
    }


def _detail_to_response(detail) -> dict:
    """Map SchemeDetail domain model to API response."""
    s = detail.scheme
    return {
        "scheme_id": s.scheme_id,
        "name": s.name,
        "short_name": s.short_name,
        "description": s.description,
        "ministry": s.ministry,
        "department": s.department,
        "level": s.level,
        "status": s.status,
        "eligibility_summary": s.eligibility_summary,
        "official_url": s.official_url,
        "application_url": s.application_url,
        "aadhaar_requirement": s.aadhaar_requirement,
        "data_version": s.data_version,
        "last_verified_at": str(s.last_verified_at) if s.last_verified_at else None,
        "aliases": detail.aliases,
        "applicable_states": detail.states if detail.states else None,
        "applicable_crops": detail.crops if detail.crops else None,
        "target_beneficiaries": detail.beneficiaries,
        "benefits": [
            {
                "type": b.benefit_type,
                "amount": b.amount,
                "description": b.description,
                "source_text": b.source_text,
            }
            for b in detail.benefits
        ],
        "eligibility_rules": [
            {
                "field": r.field_name,
                "operator": r.operator,
                "value": r.value_json,
                "logical_group": r.logical_group,
                "required": r.required,
                "source_text": r.source_text,
            }
            for r in detail.eligibility_rules
        ],
        "documents": [
            {
                "name": d.name,
                "mandatory": d.mandatory,
                "description": d.description,
            }
            for d in detail.documents
        ],
        "application_steps": [
            {
                "step_number": st.step_number,
                "description": st.description,
                "mode": st.mode,
            }
            for st in detail.application_steps
        ],
        "sources": [
            {
                "source_id": src.source_id,
                "url": src.url,
                "source_type": src.source_type,
                "retrieved_at": str(src.retrieved_at) if src.retrieved_at else None,
                "is_primary": src.is_primary,
            }
            for src in detail.sources
        ],
    }
