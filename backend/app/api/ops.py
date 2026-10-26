"""
Administrator operations API (docs/ADMIN_OPERATIONS.md).

ADMIN only, checked in each route's dependency and again in the services. State
changes (POST) need the X-CSRF-Token header. Inputs are validated strictly (unknown
fields rejected); jobs run one at a time, dry run by default, and a real run needs an
explicit confirmation. Every action is audited with the request's correlation id
(returned in the X-Request-ID header).
"""

from typing import Annotated, Any, Dict, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field, StrictBool, field_validator

from app.api.deps import require
from app.core import request_context
from app.core.exceptions import ConfigurationError, DatabaseError
from app.core.permissions import Permission, Principal
from app.models.saved_scheme_schemas import clean_text
from app.services import admin_jobs, ops_service

router = APIRouter(prefix="/admin/ops", tags=["Administration — operations"])

JobIdPath = Annotated[str, Path(pattern=r"^[0-9a-f\-]{36}$")]


class JobRequest(BaseModel):
    model_config = {"extra": "forbid"}

    kind: Literal["IMPORT_CORPUS", "REBUILD_GRAPH", "PUBLISH_CHANGES"]
    batch_id: Optional[str] = Field(default=None, pattern=r"^[0-9a-f\-]{36}$",
                                    description="PUBLISH_CHANGES only: the reviewed change batch")
    dry_run: StrictBool = True
    reason: str = Field(min_length=5, max_length=300, description="Why (kept in the audit log)")
    confirm: Optional[str] = Field(default=None, max_length=30,
                                   description="Required for a real run: the job kind, e.g. IMPORT_CORPUS")

    @field_validator("reason")
    @classmethod
    def _v_reason(cls, v):
        return clean_text(v, multiline=False)


async def _call(coro):
    try:
        return await coro
    except admin_jobs.JobRejected as exc:
        code = status.HTTP_409_CONFLICT if exc.code == "JOB_IN_PROGRESS" else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=code, detail={"code": exc.code, "message": exc.message})
    except (DatabaseError, ConfigurationError):
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={
            "code": "OPS_UNAVAILABLE", "message": "The database is unavailable; try again shortly."})


@router.get("/overview", summary="Health, corpus, ingestion, graph sync, reviews, recent errors")
async def overview(principal: Principal = Depends(require(Permission.OPS_READ))) -> Dict[str, Any]:
    return await ops_service.overview(principal)


@router.get("/errors", summary="Recent operational errors (redacted, this process)")
async def errors(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=500),
    principal: Principal = Depends(require(Permission.OPS_READ)),
) -> Dict[str, Any]:
    return ops_service.recent_errors(principal, limit, offset)


@router.get("/conflicts", summary="Source conflicts, rule conflicts and flagged schemes")
async def conflicts(principal: Principal = Depends(require(Permission.OPS_READ))) -> Dict[str, Any]:
    return await ops_service.conflicts(principal)


@router.post("/validate", summary="Validate scheme data (read-only; audited)")
async def validate(principal: Principal = Depends(require(Permission.OPS_VALIDATE))) -> Dict[str, Any]:
    return await _call(ops_service.validate(principal))


@router.get("/jobs", summary="Admin jobs, newest first")
async def jobs(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
    principal: Principal = Depends(require(Permission.OPS_READ)),
) -> Dict[str, Any]:
    return await _call(ops_service.list_jobs(principal, limit, offset))


@router.get("/jobs/{job_id}", summary="One admin job")
async def job(job_id: JobIdPath, principal: Principal = Depends(require(Permission.OPS_READ))) -> Dict[str, Any]:
    found = await _call(ops_service.get_job(principal, job_id))
    if not found:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "Job not found."})
    return found


@router.post("/jobs", status_code=status.HTTP_202_ACCEPTED,
             summary="Start an ingestion or graph-rebuild job (dry run by default)")
async def start_job(
    req: JobRequest,
    background: BackgroundTasks,
    principal: Principal = Depends(require(Permission.OPS_RUN_JOBS)),
) -> Dict[str, Any]:
    """
    One job at a time (409 otherwise). A real run (``dry_run: false``) needs ``confirm``
    equal to ``kind``. Poll ``GET /admin/ops/jobs/{id}`` for the result.
    """
    job = await _call(admin_jobs.start_job(principal, req.kind, req.dry_run, req.reason, req.confirm, req.batch_id))
    background.add_task(admin_jobs.run_job, job["id"], principal, request_context.current())
    return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in job.items()}


# ─── Live official-source checks (docs/LIVE_VERIFICATION.md) ──────────────────

@router.get("/live-sources", summary="Official pages checked at query time: new, updated, missing, unparseable")
async def live_sources(
    change_status: Optional[Literal["NEW", "UNCHANGED", "UPDATED", "INCOMPLETE", "UNPARSEABLE", "MISSING",
                                    "FAILED"]] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0, le=100_000),
    principal: Principal = Depends(require(Permission.OPS_READ)),
) -> Dict[str, Any]:
    """
    Provenance of every official page seen by live checks: last attempt (status, HTTP code, time),
    last known-good extraction time and quality, and how it changed. UPDATED pages are candidates for
    the verified scheme-update process (docs/SCHEME_UPDATES.md) — nothing here changes scheme data.
    """
    from app.database.repositories import live_snapshot_repository as repo
    rows, total = await _call(repo.list_recent(change_status, limit, offset))
    return {"items": [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()} for r in rows],
            "total": total}
