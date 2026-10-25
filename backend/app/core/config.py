"""
Centralized configuration management using Pydantic Settings.

All environment variables are loaded here. The application should NOT crash
at import time if credentials are missing — instead, services validate
their required config at usage time and return meaningful errors.
"""

from pathlib import Path
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field

# Single source of truth for the application version (Phase 7 release candidate)
APP_VERSION = "1.0.0"

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # --- Database ---
    DATABASE_URL: Optional[str] = Field(
        default=None,
        description="Primary PostgreSQL connection string (local or Neon)"
    )
    NEON_DATABASE_URL: Optional[str] = Field(
        default=None,
        description="Legacy: PostgreSQL connection string for Neon DB (fallback if DATABASE_URL unset)"
    )
    DB_MIN_SIZE: int = Field(default=1, description="Connection pool minimum size")
    DB_MAX_SIZE: int = Field(default=5, description="Connection pool maximum size")

    @property
    def effective_database_url(self) -> Optional[str]:
        """Return DATABASE_URL if set, else fall back to NEON_DATABASE_URL."""
        return self.DATABASE_URL or self.NEON_DATABASE_URL

    # --- AI & Search APIs ---
    GROQ_API_KEY: Optional[str] = Field(
        default=None,
        description="API key for Groq LLM"
    )
    GROQ_MODEL: str = Field(
        default="openai/gpt-oss-20b",
        description="Groq model id (Groq retires models; list yours at https://api.groq.com/openai/v1/models)"
    )
    TAVILY_API_KEY: Optional[str] = Field(
        default=None,
        description="API key for Tavily web search"
    )
    SARVAM_API_KEY: Optional[str] = Field(
        default=None,
        description="API key for Sarvam AI voice services"
    )

    # --- Server ---
    BACKEND_HOST: str = Field(default="0.0.0.0")
    BACKEND_PORT: int = Field(default=8000)
    ENVIRONMENT: str = Field(
        default="development",
        description="Runtime environment: development, staging, production (demo is set by scripts/demo_server.py)"
    )

    # --- Logging ---
    LOG_LEVEL: str = Field(default="INFO")

    # --- Timeouts (seconds) ---
    SARVAM_TIMEOUT: float = Field(default=30.0)
    GROQ_TIMEOUT: float = Field(default=30.0, description="Per-request Groq LLM timeout")
    DB_TIMEOUT: float = Field(default=10.0)

    # --- Phase 4: Retrieval channel timeouts (§26) ---
    DB_SEARCH_TIMEOUT: float = Field(
        default=5.0,
        description="Timeout for PostgreSQL scheme search"
    )
    GRAPH_SEARCH_TIMEOUT: float = Field(
        default=3.0,
        description="Timeout for Knowledge Graph search"
    )
    TAVILY_SEARCH_TIMEOUT: float = Field(
        default=10.0,
        description="Timeout for Tavily live web search"
    )

    # --- Phase 4: Candidate limits (§106, §107, §195) ---
    # Candidates are evaluated (cheap, deterministic) BEFORE truncation for display,
    # so relevant schemes are never cut off alphabetically (Phase 7 BUG-006).
    MAX_DB_RESULTS: int = Field(default=25, description="Max DB results per search")
    MAX_GRAPH_RESULTS: int = Field(default=25, description="Max graph candidates")
    MAX_WEB_RESULTS: int = Field(default=5, description="Max Tavily web results")
    MAX_CANDIDATES: int = Field(
        default=25,
        description="Max merged candidates evaluated for eligibility"
    )
    MAX_RESPONSE_SCHEMES: int = Field(
        default=25,
        description="Max ranked schemes returned to the user (NOT_ELIGIBLE / UNVERIFIABLE "
                    "results are kept so the user can see why a scheme does not apply)"
    )

    # --- Phase 4: Context window (§55) ---
    RECENT_MESSAGES_WINDOW: int = Field(
        default=10,
        description="Number of recent conversation turns to include for context"
    )

    # --- Phase 4: Profile priority (§17) ---
    PROFILE_PRIORITY: List[str] = Field(
        default=["state", "land_size_acres", "primary_crop"],
        description="Ordered list of critical fields for completeness check"
    )

    # --- Request limits ---
    MAX_MESSAGE_CHARS: int = Field(default=2000, description="Maximum chat message length")

    # --- Sessions (in-memory LangGraph checkpointer) ---
    MAX_SESSIONS: int = Field(
        default=1000,
        description="Max conversation threads kept in memory; oldest are evicted"
    )

    # --- Human review API (development-level protection, §68/§111) ---
    REVIEW_API_KEY: Optional[str] = Field(
        default=None,
        description="Reviewer API key (X-Review-Key header). Review API is disabled when unset."
    )

    # --- Upload limits ---
    MAX_AUDIO_SIZE_MB: float = Field(
        default=10.0,
        description="Maximum audio upload size in megabytes"
    )

    # --- CORS ---
    CORS_ORIGINS: List[str] = Field(
        default=["http://localhost:3000"],
        description="Allowed CORS origins"
    )

    # --- Auth / JWT ---
    JWT_SECRET_KEY: str = Field(
        default="change-me-in-production-use-a-long-random-secret",
        description="HMAC secret for signing JWTs. MUST be set in production."
    )
    JWT_ALGORITHM: str = Field(default="HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=60,
        description="Short-lived access token lifetime in minutes"
    )
    REFRESH_TOKEN_EXPIRE_DAYS: int = Field(
        default=30,
        description="Long-lived refresh token lifetime in days"
    )
    PASSWORD_RESET_EXPIRE_HOURS: int = Field(
        default=24,
        description="Password reset token lifetime in hours"
    )

    model_config = {
        "env_file": (
            str(_BACKEND_DIR / ".env"),
            str(_BACKEND_DIR.parent / ".env"),
        ),
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore",
    }


# Singleton settings instance
settings = Settings()
