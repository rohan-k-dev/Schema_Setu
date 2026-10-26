"""
Health check API routes.

Provides liveness, readiness, and combined health endpoints.
"""

from fastapi import APIRouter

from app.models.responses import HealthResponse, LivenessResponse, ReadinessResponse
from app.database.connection import is_db_available
from app.database.repositories.scheme_repository import SchemeRepository
from app.core.config import settings, APP_VERSION
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Health"])


@router.get(
    "/",
    summary="API Status",
    description="Basic API status check.",
)
async def root():
    """Root endpoint — confirms API is running."""
    return {
        "message": "SchemeSetu API is running.",
        "version": APP_VERSION,
        "environment": settings.ENVIRONMENT,
    }


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health Check",
    description="Combined health status including database connectivity.",
)
async def health_check():
    """Full health check with dependency status."""
    db_healthy = False

    if is_db_available():
        db_healthy = await SchemeRepository.health_check()

    # Knowledge Graph health
    graph_info = {"loaded": False}
    try:
        from app.services.knowledge_graph_service import graph_health_check
        graph_info = graph_health_check()
    except Exception:
        pass

    graph_ok = bool(graph_info.get("loaded"))
    status = "healthy" if db_healthy and graph_ok else "degraded"

    return HealthResponse(
        status=status,
        db_connected=db_healthy,
        graph_available=graph_ok,
        environment=settings.ENVIRONMENT,
        version=APP_VERSION,
    )


@router.get(
    "/health/live",
    response_model=LivenessResponse,
    summary="Liveness Probe",
    description="Confirms the application process is alive.",
)
async def liveness():
    """Liveness probe — if this returns, the process is alive."""
    return LivenessResponse(status="alive")


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    summary="Readiness Probe",
    description="Checks if the application and its dependencies are ready.",
)
async def readiness():
    """Readiness probe — checks all dependency availability."""
    db_ready = False
    if is_db_available():
        db_ready = await SchemeRepository.health_check()

    from app.services.knowledge_graph_service import is_graph_available
    graph_ready = is_graph_available()

    groq_configured = settings.GROQ_API_KEY is not None
    tavily_configured = settings.TAVILY_API_KEY is not None
    sarvam_configured = settings.SARVAM_API_KEY is not None

    all_ready = db_ready and groq_configured
    status = "ready" if all_ready else "not_ready"

    return ReadinessResponse(
        status=status,
        db_ready=db_ready,
        graph_ready=graph_ready,
        groq_configured=groq_configured,
        tavily_configured=tavily_configured,
        sarvam_configured=sarvam_configured,
    )
