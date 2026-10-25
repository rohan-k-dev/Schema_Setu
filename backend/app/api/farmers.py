"""
Farmers API — protected routes for farmer profile management,
saved schemes, search history, and the personalized dashboard.

All routes require a valid JWT Bearer token (via get_current_farmer_id).
Routes are under /farmers prefix.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse

from app.api.deps import get_current_farmer_id
from app.models.auth_schemas import (
    DashboardResponse,
    ProfileResponse,
    ProfileUpdateRequest,
    SavedSchemeResponse,
    SaveSchemeRequest,
    SearchHistoryEntry,
)
from app.services.profile_service import (
    ProfileError,
    delete_farmer_scheme,
    get_dashboard,
    get_farmer_saved_schemes,
    get_farmer_search_history,
    get_profile,
    save_farmer_scheme,
    update_profile,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/farmers", tags=["Farmer Profile & Dashboard"])


def _profile_error(exc: ProfileError) -> HTTPException:
    status_code = (
        status.HTTP_404_NOT_FOUND if exc.code == "NOT_FOUND"
        else status.HTTP_403_FORBIDDEN if exc.code == "CONSENT_REQUIRED"
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message})


# ─── Dashboard ─────────────────────────────────────────────────────────────────

@router.get(
    "/me/dashboard",
    response_model=DashboardResponse,
    summary="Personalized farmer dashboard",
)
async def dashboard(
    farmer_id: str = Depends(get_current_farmer_id),
) -> DashboardResponse:
    """
    Return the complete dashboard payload for the authenticated farmer:

    - Account info
    - Saved profile + completeness percentage
    - List of missing eligibility fields
    - Bookmarked schemes
    - 10 most recent searches
    """
    try:
        return await get_dashboard(farmer_id)
    except ProfileError as exc:
        raise _profile_error(exc)


# ─── Profile ───────────────────────────────────────────────────────────────────

@router.get(
    "/me/profile",
    response_model=ProfileResponse,
    summary="Get the authenticated farmer's saved profile",
)
async def get_my_profile(
    farmer_id: str = Depends(get_current_farmer_id),
):
    """Return the farmer's persisted eligibility profile, or 404 if not set yet."""
    profile = await get_profile(farmer_id)
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NO_PROFILE", "message": "Profile not yet saved."},
        )
    return profile


@router.put(
    "/me/profile",
    response_model=ProfileResponse,
    summary="Save / update the farmer profile",
)
async def update_my_profile(
    req: ProfileUpdateRequest,
    farmer_id: str = Depends(get_current_farmer_id),
) -> ProfileResponse:
    """
    Create or update the farmer's eligibility profile.

    **Consent is required** — set ``consent_given: true`` in the request body.
    Fields are validated and canonicalised (e.g. state abbreviations are
    expanded, crop synonyms are normalised).
    """
    try:
        return await update_profile(farmer_id, req)
    except ProfileError as exc:
        raise _profile_error(exc)


# ─── Saved schemes ─────────────────────────────────────────────────────────────

@router.get(
    "/me/saved-schemes",
    response_model=list[SavedSchemeResponse],
    summary="Get bookmarked schemes",
)
async def get_saved(
    farmer_id: str = Depends(get_current_farmer_id),
):
    """Return all schemes the farmer has bookmarked, newest first."""
    return await get_farmer_saved_schemes(farmer_id)


@router.post(
    "/me/saved-schemes",
    response_model=SavedSchemeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Bookmark a scheme",
)
async def save_scheme_endpoint(
    req: SaveSchemeRequest,
    farmer_id: str = Depends(get_current_farmer_id),
) -> SavedSchemeResponse:
    """Save or update a bookmarked scheme for the authenticated farmer."""
    try:
        return await save_farmer_scheme(farmer_id, req)
    except ProfileError as exc:
        raise _profile_error(exc)


@router.delete(
    "/me/saved-schemes/{scheme_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a bookmarked scheme",
)
async def delete_scheme(
    scheme_id: str,
    farmer_id: str = Depends(get_current_farmer_id),
):
    """Remove a scheme from the farmer's bookmarks."""
    deleted = await delete_farmer_scheme(farmer_id, scheme_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Saved scheme not found."},
        )


# ─── Search history ─────────────────────────────────────────────────────────────

@router.get(
    "/me/search-history",
    response_model=list[SearchHistoryEntry],
    summary="Get recent search queries",
)
async def get_searches(
    limit: int = Query(default=10, ge=1, le=50),
    farmer_id: str = Depends(get_current_farmer_id),
):
    """Return the *limit* most recent search queries for the authenticated farmer."""
    return await get_farmer_search_history(farmer_id, limit)
