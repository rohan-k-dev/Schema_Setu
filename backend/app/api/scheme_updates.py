"""
Scheme-update review and notification operations — administrators only
(docs/SCHEME_UPDATES.md). Publishing approved changes is the admin job
PUBLISH_CHANGES (POST /admin/ops/jobs with batch_id).
"""

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field, StrictBool

from app.api.deps import require
from app.core.exceptions import ConfigurationError, DatabaseError
from app.core.permissions import Permission, Principal
from app.database.repositories import notification_repository as notif_repo
from app.models.saved_scheme_schemas import clean_text
from app.services import notification_service, scheme_update_service as svc

router = APIRouter(prefix="/admin", tags=["Administration — scheme updates"])
review_perm = require(Permission.SCHEME_CHANGES_REVIEW)
notif_perm = require(Permission.NOTIFICATIONS_ADMIN)

BatchIdPath = Annotated[str, Path(pattern=r"^[0-9a-f\-]{36}$")]

_STATUS = {"NOT_FOUND": 404, "NOT_PENDING": 409, "NOT_OPEN": 409, "CONFIRMATION_REQUIRED": 422,
           "BAD_SOURCE": 422, "BAD_JSON": 422, "TOO_LARGE": 413}


def _iso(row: dict) -> dict:
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items()}


async def _call(coro):
    try:
        return await coro
    except svc.UpdateRejected as exc:
        raise HTTPException(status_code=_STATUS.get(exc.code, 400), detail={"code": exc.code, "message": exc.message})
    except (DatabaseError, ConfigurationError):
        raise HTTPException(status_code=503, detail={"code": "UPDATES_UNAVAILABLE",
                                                     "message": "The database is unavailable."})


class DetectRequest(BaseModel):
    model_config = {"extra": "forbid"}
    source: str = Field(min_length=6, max_length=105, description="A .json file in data/incoming/")


class ReviewRequest(BaseModel):
    model_config = {"extra": "forbid"}
    decision: Literal["APPROVED", "REJECTED"]
    note: Optional[str] = Field(default=None, max_length=1000)
    confirm_consequential: StrictBool = False

    def clean_note(self) -> Optional[str]:
        return clean_text(self.note, multiline=True) if self.note else None


@router.get("/scheme-changes/sources", summary="Candidate files in data/incoming/")
async def sources(principal: Principal = Depends(review_perm)):
    return {"items": svc.list_incoming()}


@router.post("/scheme-changes/detect", summary="Compare a candidate file with the verified corpus")
async def detect(req: DetectRequest, principal: Principal = Depends(review_perm)):
    return await _call(svc.detect(principal, req.source))


@router.get("/scheme-changes/batches", summary="Detection batches, newest first")
async def batches(limit: int = Query(default=20, ge=1, le=100), offset: int = Query(default=0, ge=0, le=100_000),
                  principal: Principal = Depends(review_perm)):
    rows, total = await _call(svc.batches(principal, limit, offset))
    return {"items": [_iso(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/scheme-changes", summary="Detected changes (consequential first)")
async def list_changes(batch_id: Optional[str] = Query(default=None, pattern=r"^[0-9a-f\-]{36}$"),
                       status: Optional[Literal["PENDING", "APPROVED", "REJECTED", "PUBLISHED", "DISCARDED"]] = None,
                       limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0, le=100_000),
                       principal: Principal = Depends(review_perm)):
    rows, total = await _call(svc.changes(principal, batch_id, status, limit, offset))
    return {"items": [_iso(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.post("/scheme-changes/{change_id}/review", summary="Approve or reject one change")
async def review(change_id: Annotated[int, Path(ge=1, le=2_147_483_647)], req: ReviewRequest,
                 principal: Principal = Depends(review_perm)):
    return _iso(await _call(svc.review(principal, change_id, req.decision, req.clean_note(),
                                       req.confirm_consequential)))


@router.post("/scheme-changes/batches/{batch_id}/discard", status_code=204, summary="Discard an open batch")
async def discard(batch_id: BatchIdPath, principal: Principal = Depends(review_perm)):
    await _call(svc.discard(principal, batch_id))


@router.get("/notifications/deliveries", summary="Delivery status (e-mail / SMS)")
async def deliveries(status: Optional[Literal["PENDING", "SENDING", "SENT", "DELIVERED", "UNDELIVERED", "FAILED",
                                              "GAVE_UP", "SKIPPED"]] = None,
                     channel: Optional[Literal["EMAIL", "SMS"]] = None,
                     limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0, le=100_000),
                     principal: Principal = Depends(notif_perm)):
    rows, total = await _call(notif_repo.list_deliveries(status, channel, limit, offset))
    return {"items": [_iso(r) for r in rows], "total": total, "counts": await _call(notif_repo.delivery_counts())}


@router.post("/notifications/dispatch", summary="Send due deliveries now (retries included)")
async def dispatch(principal: Principal = Depends(notif_perm)):
    result = await _call(notification_service.dispatch_due())
    from app.database.repositories import audit_repository
    await audit_repository.record(principal, "NOTIFICATIONS_DISPATCHED", "notifications", None, result)
    return result
