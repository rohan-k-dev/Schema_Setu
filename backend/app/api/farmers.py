"""
Farmers API â€” protected routes for farmer profile management,
saved schemes, search history, and the personalized dashboard.

All routes require a signed-in session (HttpOnly cookie) whose role holds the route's
own-data permission (require_own, docs/RBAC.md); PUT/PATCH/POST/DELETE also need the
X-CSRF-Token header. Routes are under /farmers/me/...:
the account is always the signed-in one â€” no route accepts another farmer's id.
"""

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status

from app.api.deps import require, require_own
from app.core.permissions import Permission, Principal
from app.core.exceptions import ConfigurationError, DatabaseError
from app.models.auth_schemas import (
    DashboardResponse,
    ProfileResponse,
    ProfileUpdateRequest,
    SaveSchemeRequest,
    SearchHistoryEntry,
)
from app.models.dashboard_schemas import EligibilityBasis, EligibilityDashboard
from app.models.saved_scheme_schemas import (
    ChecklistItemUpdateRequest,
    MilestoneCreateRequest,
    SavedSchemeDetail,
    SavedSchemeSummary,
    SavedSchemeUpdateRequest,
    SaveSchemeResult,
)
from app.services import saved_scheme_service as saved_svc
from app.services.dashboard_service import DashboardUnavailable, compute_dashboard, get_basis
from app.services.profile_service import (
    ProfileError,
    clear_search_history,
    delete_search,
    get_dashboard,
    get_farmer_search_history,
    get_profile,
    update_profile,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/farmers", tags=["Farmer Profile & Dashboard"])


def _profile_error(exc: ProfileError) -> HTTPException:
    status_code = (
        status.HTTP_404_NOT_FOUND if exc.code == "NOT_FOUND"
        else status.HTTP_403_FORBIDDEN if exc.code == "CONSENT_REQUIRED"
        else status.HTTP_409_CONFLICT if exc.code == "CONFLICT"
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message})


# â”€â”€â”€ Dashboard â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get(
    "/me/dashboard",
    response_model=DashboardResponse,
    summary="Personalized farmer dashboard",
)
async def dashboard(
    farmer_id: str = Depends(require_own(Permission.PROFILE_OWN_READ)),
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


# â”€â”€â”€ Profile â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get(
    "/me/profile",
    response_model=ProfileResponse,
    summary="Get the authenticated farmer's saved profile",
)
async def get_my_profile(
    farmer_id: str = Depends(require_own(Permission.PROFILE_OWN_READ)),
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
    farmer_id: str = Depends(require_own(Permission.PROFILE_OWN_WRITE)),
) -> ProfileResponse:
    """
    Create or update the farmer's eligibility profile (partial update).

    **Consent is required** â€” set ``consent_given: true`` on the first save.
    Fields left out are unchanged; fields sent as ``null`` become unknown.
    Fields are validated and canonicalised (e.g. state abbreviations are expanded,
    land is converted to acres); invalid values and unexpected fields give 422.
    Send ``expected_version`` (from the last GET) to get 409 instead of silently
    overwriting a newer edit.
    """
    try:
        return await update_profile(farmer_id, req)
    except ProfileError as exc:
        raise _profile_error(exc)


# â”€â”€â”€ Saved schemes + application checklists (docs/SAVED_SCHEMES.md) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
#
# Progress is user-reported: no government application-tracking system is connected.

SchemeIdPath = Annotated[str, Path(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_\-]+$")]
ItemIdPath = Annotated[int, Path(ge=1, le=2_147_483_647)]


def _saved_error(exc: saved_svc.SavedSchemeError) -> HTTPException:
    status_code = {
        "NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "NOT_SAVED": status.HTTP_404_NOT_FOUND,
        "SCHEME_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "ITEM_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "SCHEME_INACTIVE": status.HTTP_409_CONFLICT,
        "NOT_DELETABLE": status.HTTP_409_CONFLICT,
        "LIMIT_REACHED": status.HTTP_409_CONFLICT,
    }.get(exc.code, status.HTTP_400_BAD_REQUEST)
    return HTTPException(status_code=status_code, detail={"code": exc.code, "message": exc.message})


async def _saved_call(coro):
    """Run a saved-scheme service call; map its errors (and a database outage) to HTTP."""
    try:
        return await coro
    except saved_svc.SavedSchemeError as exc:
        raise _saved_error(exc)
    except (DatabaseError, ConfigurationError):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={
            "code": "SAVED_SCHEMES_UNAVAILABLE",
            "message": "Saved schemes are unavailable right now. Please try again shortly."})


@router.get(
    "/me/saved-schemes",
    response_model=list[SavedSchemeSummary],
    summary="Get saved schemes with user-reported progress",
)
async def get_saved(
    farmer_id: str = Depends(require_own(Permission.SAVED_SCHEMES_OWN_READ)),
):
    """Return all schemes the farmer has saved, newest first, with checklist progress."""
    return await _saved_call(saved_svc.list_saved_schemes(farmer_id))


@router.post(
    "/me/saved-schemes",
    response_model=SaveSchemeResult,
    status_code=status.HTTP_201_CREATED,
    summary="Save a scheme (creates its application checklist)",
)
async def save_scheme_endpoint(
    req: SaveSchemeRequest,
    response: Response,
    farmer_id: str = Depends(require_own(Permission.SAVED_SCHEMES_OWN_WRITE)),
) -> SaveSchemeResult:
    """
    Save a scheme from SchemeSetu's database: 201 with a new checklist, or 200 with
    ``created: false`` if it was already saved (nothing is changed or duplicated).
    Unknown schemes give 404; inactive ones 409.
    """
    result = await _saved_call(saved_svc.save_scheme(farmer_id, req))
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return result


@router.get(
    "/me/saved-schemes/{scheme_id}",
    response_model=SavedSchemeDetail,
    summary="A saved scheme with its checklist",
)
async def get_saved_one(
    scheme_id: SchemeIdPath,
    farmer_id: str = Depends(require_own(Permission.SAVED_SCHEMES_OWN_READ)),
) -> SavedSchemeDetail:
    """The checklist is brought up to date first if the scheme's information changed."""
    return await _saved_call(saved_svc.get_saved_scheme(farmer_id, scheme_id))


@router.patch(
    "/me/saved-schemes/{scheme_id}",
    response_model=SavedSchemeDetail,
    summary="Update notes / application reference, or acknowledge a scheme update",
)
async def update_saved_one(
    req: SavedSchemeUpdateRequest,
    scheme_id: SchemeIdPath,
    farmer_id: str = Depends(require_own(Permission.SAVED_SCHEMES_OWN_WRITE)),
) -> SavedSchemeDetail:
    """Fields left out are unchanged; null clears notes or the application reference."""
    return await _saved_call(saved_svc.update_saved_scheme(farmer_id, scheme_id, req))


@router.delete(
    "/me/saved-schemes/{scheme_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a saved scheme (and its checklist)",
)
async def delete_scheme(
    scheme_id: SchemeIdPath,
    farmer_id: str = Depends(require_own(Permission.SAVED_SCHEMES_OWN_WRITE)),
):
    """Remove a scheme from the farmer's saved schemes. 404 if it wasn't saved."""
    deleted = await _saved_call(saved_svc.unsave_scheme(farmer_id, scheme_id))
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Saved scheme not found."},
        )


@router.patch(
    "/me/saved-schemes/{scheme_id}/checklist/{item_id}",
    response_model=SavedSchemeDetail,
    summary="Mark a checklist item complete / incomplete, or set its note",
)
async def update_checklist_item(
    req: ChecklistItemUpdateRequest,
    scheme_id: SchemeIdPath,
    item_id: ItemIdPath,
    farmer_id: str = Depends(require_own(Permission.SAVED_SCHEMES_OWN_WRITE)),
) -> SavedSchemeDetail:
    """Another farmer's item gives 404, the same as a missing one."""
    return await _saved_call(saved_svc.update_item(farmer_id, scheme_id, item_id, req))


@router.post(
    "/me/saved-schemes/{scheme_id}/checklist",
    response_model=SavedSchemeDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Add your own milestone",
)
async def add_checklist_milestone(
    req: MilestoneCreateRequest,
    scheme_id: SchemeIdPath,
    farmer_id: str = Depends(require_own(Permission.SAVED_SCHEMES_OWN_WRITE)),
) -> SavedSchemeDetail:
    """A later step you want to record yourself, e.g. "Field verification done"."""
    return await _saved_call(saved_svc.add_milestone(farmer_id, scheme_id, req))


@router.delete(
    "/me/saved-schemes/{scheme_id}/checklist/{item_id}",
    response_model=SavedSchemeDetail,
    summary="Delete one of your own milestones",
)
async def delete_checklist_milestone(
    scheme_id: SchemeIdPath,
    item_id: ItemIdPath,
    farmer_id: str = Depends(require_own(Permission.SAVED_SCHEMES_OWN_WRITE)),
) -> SavedSchemeDetail:
    """Only milestones you added can be deleted (409 for items from the scheme)."""
    return await _saved_call(saved_svc.delete_milestone(farmer_id, scheme_id, item_id))


# â”€â”€â”€ Search history â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get(
    "/me/search-history",
    response_model=list[SearchHistoryEntry],
    summary="Get recent search queries",
)
async def get_searches(
    response: Response,
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=1000),
    farmer_id: str = Depends(require_own(Permission.HISTORY_OWN_READ)),
):
    """
    Return the farmer's recent searches, newest first (*limit* from *offset*).
    The total number kept is in the ``X-Total-Count`` header. Searches are kept
    only as the retention policy allows (docs/DASHBOARD.md).
    """
    entries, total = await get_farmer_search_history(farmer_id, limit, offset)
    response.headers["X-Total-Count"] = str(total)
    return entries


@router.delete(
    "/me/search-history/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one search from history",
)
async def delete_search_entry(
    entry_id: int = Path(ge=1, le=2_147_483_647),
    farmer_id: str = Depends(require_own(Permission.HISTORY_OWN_DELETE)),
):
    """Delete one of your own searches. Another farmer's entry gives 404, like a missing one."""
    if not await delete_search(farmer_id, entry_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": "Search not found."},
        )


@router.delete(
    "/me/search-history",
    summary="Clear search history",
)
async def clear_searches(
    farmer_id: str = Depends(require_own(Permission.HISTORY_OWN_DELETE)),
) -> dict:
    """Delete all of the farmer's searches."""
    return {"deleted": await clear_search_history(farmer_id)}


# â”€â”€â”€ Eligibility (deterministic engine, saved profile) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _unavailable() -> HTTPException:
    return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={
        "code": "ELIGIBILITY_UNAVAILABLE",
        "message": "Scheme data is unavailable right now. Please try again shortly."})


@router.get(
    "/me/eligibility",
    response_model=EligibilityDashboard,
    summary="Eligibility for every active scheme, from the saved profile",
)
async def my_eligibility(
    status_filter: Optional[Literal["ELIGIBLE", "NOT_ELIGIBLE", "NEEDS_MORE_INFORMATION", "UNVERIFIABLE"]] = Query(
        default=None, alias="status"),
    page: int = Query(default=1, ge=1, le=1000),
    page_size: int = Query(default=10, ge=1, le=50),
    farmer_id: str = Depends(require_own(Permission.ELIGIBILITY_OWN_READ)),
) -> EligibilityDashboard:
    """
    Check every active scheme against the saved profile with the deterministic
    eligibility engine (no LLM). Returns counts per status, one page of ranked
    results, the details still missing, conflicting details, and the ``basis`` the
    result was computed from (compare with ``/me/eligibility/basis`` to detect staleness).
    """
    try:
        return await compute_dashboard(farmer_id, status_filter, page, page_size)
    except DashboardUnavailable:
        raise _unavailable()


@router.get(
    "/me/eligibility/basis",
    response_model=EligibilityBasis,
    summary="Current basis of the eligibility result (for staleness checks)",
)
async def my_eligibility_basis(
    farmer_id: str = Depends(require_own(Permission.ELIGIBILITY_OWN_READ)),
) -> EligibilityBasis:
    """Profile version + fingerprint of scheme records and rules + engine version."""
    try:
        return await get_basis(farmer_id)
    except DashboardUnavailable:
        raise _unavailable()


# ─── Human-review cases raised by your own searches (docs/HUMAN_REVIEW.md) ─────

@router.get("/me/review-cases", summary="Status of checks by our team on your results")
async def my_review_cases(principal: Principal = Depends(require(Permission.REVIEW_OWN_READ))):
    """
    Cases your chat or voice searches raised for a person to check, in plain language: which
    scheme, why, whether it is still open and the outcome. No reviewer names, notes or evidence.
    """
    from app.services import review_workflow
    try:
        items = await review_workflow.cases_for_farmer(principal.account_pk)
    except Exception as exc:
        logger.error(f"Review cases unavailable: {type(exc).__name__}")
        raise HTTPException(status_code=503, detail={"code": "REVIEW_UNAVAILABLE",
                                                     "message": "Couldn't load this right now. Please try again."})
    for i in items:
        for k in ("opened_at", "updated_at"):
            if hasattr(i[k], "isoformat"):
                i[k] = i[k].isoformat()
    return {"items": items, "open": sum(1 for i in items if i["open"])}

