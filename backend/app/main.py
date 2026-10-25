"""
SchemeSetu API — Main FastAPI Application

This is the application entry point. It only:
- Creates the FastAPI app
- Configures middleware (CORS)
- Manages application lifespan (DB startup/shutdown)
- Includes API routers

All business logic lives in services/, graph/, and database/ modules.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings, APP_VERSION
from app.core.logging import setup_logging, get_logger
from app.core.exceptions import SchemSetuError
from app.database.connection import init_db, close_db
from app.api import chat, voice, health, schemes, review, auth, farmers

# Initialize logging before anything else
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — manages startup and shutdown."""
    logger.info(f"Starting SchemeSetu API (environment={settings.ENVIRONMENT})")
    await init_db()
    # Load corpus for local scheme search
    try:
        from app.ingestion.corpus_loader import get_corpus_loader
        loader = get_corpus_loader()
        logger.info(f"Corpus loaded: {loader.scheme_count} schemes")
    except Exception as e:
        logger.warning(f"Corpus load failed (non-fatal): {e}")
    # Load Knowledge Graph (Phase 3) — graceful degradation
    try:
        from app.services.knowledge_graph_service import init_knowledge_graph
        if init_knowledge_graph():
            logger.info("Knowledge Graph loaded successfully.")
        else:
            logger.warning("Knowledge Graph not available (non-fatal).")
    except Exception as e:
        logger.warning(f"Knowledge Graph load failed (non-fatal): {e}")
    logger.info("Application startup complete.")
    yield
    await close_db()
    logger.info("Application shutdown complete.")


# --- Create the FastAPI app ---
app = FastAPI(
    title="SchemeSetu API",
    description="AI-powered government scheme discovery for Indian farmers",
    version=APP_VERSION,
    lifespan=lifespan,
)

# --- CORS Middleware ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Global exception handler for application errors ---
@app.exception_handler(SchemSetuError)
async def schemesetu_error_handler(request: Request, exc: SchemSetuError):
    """Convert application exceptions to structured JSON responses."""
    logger.error(f"Application error: [{exc.code}] {exc.message}")
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error": {
                "code": exc.code,
                "message": exc.message,
            },
        },
    )


# --- Include API routers ---
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(voice.router)
app.include_router(schemes.router)
app.include_router(review.router)
app.include_router(auth.router)
app.include_router(farmers.router)


# --- Language registry endpoint (§11) ---
@app.get("/languages", tags=["Languages"])
async def get_languages():
    """Return supported language list for frontend selector."""
    from app.localization.languages import get_language_for_frontend
    return {"languages": get_language_for_frontend()}