"""
Centralized configuration management using Pydantic Settings.

All environment variables are loaded here. The application should NOT crash
at import time if credentials are missing — instead, services validate
their required config at usage time and return meaningful errors.
"""

from pathlib import Path
from typing import List, Literal, Optional
from pydantic_settings import BaseSettings
from pydantic import Field, field_validator

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
    MAX_DB_RESULTS: int = Field(default=60, description="Max DB results per search (all schemes applicable to a "
                                "state are evaluated; the UI pages the alternatives)")
    MAX_GRAPH_RESULTS: int = Field(default=25, description="Max graph candidates")
    MAX_WEB_RESULTS: int = Field(default=5, description="Max Tavily web results")
    MAX_CANDIDATES: int = Field(
        default=60,
        description="Max merged candidates evaluated for eligibility"
    )
    MAX_RESPONSE_SCHEMES: int = Field(
        default=60,
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

    # --- Accounts: server-managed sessions (HttpOnly cookie) ---
    SESSION_COOKIE_NAME: str = Field(default="ss_session")
    SESSION_IDLE_MINUTES: int = Field(
        default=720, description="Session ends after this much inactivity (12 h)")
    SESSION_ABSOLUTE_HOURS: int = Field(
        default=168, description="Session ends this long after login regardless of activity (7 days)")
    COOKIE_SECURE: Optional[bool] = Field(
        default=None,
        description="Secure cookie flag. Default: on when ENVIRONMENT=production (HTTPS required)")
    SESSION_SECRET: Optional[str] = Field(
        default=None,
        description="Key for deriving CSRF tokens. Unset = random per process (tokens refresh on restart)")

    # --- Accounts: e-mail verification and password reset ---
    REQUIRE_EMAIL_VERIFICATION: bool = Field(
        default=True, description="Users must verify their e-mail before they can log in")
    EMAIL_VERIFY_EXPIRE_HOURS: int = Field(default=24)
    PASSWORD_RESET_EXPIRE_MINUTES: int = Field(default=30)
    FRONTEND_BASE_URL: str = Field(
        default="http://localhost:3000", description="Used to build links in e-mails")

    # --- Accounts: brute-force protection ---
    LOGIN_MAX_FAILURES: int = Field(default=5, description="Failed logins before a temporary lock")
    LOGIN_LOCK_MINUTES: int = Field(default=15)
    RATE_LIMIT_ENABLED: bool = Field(default=True)

    # --- Outgoing e-mail (SMTP). Unset in development: e-mails are written to the log ---
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM: str = "SchemeSetu <no-reply@schemesetu.local>"
    SMTP_STARTTLS: bool = True

    # --- Staff sessions and the reviewer access policy (docs/HUMAN_REVIEW.md) ---
    STAFF_SESSION_IDLE_MINUTES: int = Field(default=30, ge=5, le=720,
                                            description="Idle timeout for REVIEWER / ADMIN sessions")
    STAFF_SESSION_ABSOLUTE_HOURS: int = Field(default=12, ge=1, le=168,
                                              description="Absolute lifetime of REVIEWER / ADMIN sessions")
    REAUTH_WINDOW_MINUTES: int = Field(default=10, ge=1, le=120,
                                       description="Sensitive actions need a sign-in or password re-entry this recent")
    REVIEW_SELF_ASSIGN: bool = Field(default=True, description="Approved reviewers may take unassigned pending "
                                     "cases; False = only administrators assign")
    REVIEW_GRANT_MAX_HOURS: int = Field(default=168, ge=1, le=720)
    REVIEW_VIEWS_PER_10_MIN: int = Field(default=120, ge=10, le=2000,
                                         description="Case-detail views per reviewer per 10 minutes (anti-scraping)")

    # --- Query-time discovery and verification (docs/LIVE_VERIFICATION.md) ---
    LIVE_VERIFICATION_ENABLED: bool = Field(default=True, description="Search and verify official sources per question")
    LIVE_BUDGET_SECONDS: float = Field(default=9.0, ge=1, le=60, description="Time budget for the live check of one question")
    LIVE_MAX_SOURCES: int = Field(default=8, ge=1, le=30, description="Official pages fetched per question at most")
    LIVE_DIRECT_FETCH_SCHEMES: int = Field(default=4, ge=0, le=20,
                                           description="Top stored schemes whose official pages are re-checked per question")
    LIVE_TAVILY_RESULTS: int = Field(default=5, ge=1, le=20, description="Results per scoped Tavily search")
    LIVE_FETCH_TIMEOUT: float = Field(default=6.0, ge=1, le=30)
    LIVE_MAX_BYTES: int = Field(default=3_000_000, ge=10_000)
    LIVE_HOST_MIN_INTERVAL: float = Field(default=1.0, ge=0, le=30, description="Seconds between requests to one host")
    LIVE_USER_AGENT: str = Field(default="SchemeSetuBot/1.0 (scheme verification for Indian farmers; "
                                         "respects robots.txt)")

    # --- Data retention (docs/PRIVACY.md) ---
    RETENTION_SESSION_DAYS: int = Field(default=30, ge=1, description="Delete sessions this long after they ended")
    RETENTION_TOKEN_DAYS: int = Field(default=7, ge=1, description="Delete used / expired one-time tokens after this")
    RETENTION_NOTIFICATION_DAYS: int = Field(default=365, ge=30, description="Delete in-app notifications after this")
    RETENTION_REVIEW_CASE_DAYS: int = Field(default=365, ge=30,
                                            description="Anonymise closed review cases after this")
    RETENTION_CHAT_DAYS: int = Field(default=365, ge=30,
                                     description="Delete saved conversations this long after their last message")
    RETENTION_PURGE_INTERVAL_HOURS: int = Field(default=24, ge=0, description="Background purge interval; 0 = off")

    # --- Scheme-update notifications (docs/SCHEME_UPDATES.md) ---
    NOTIFY_MAX_ATTEMPTS: int = Field(default=5, ge=1, le=10, description="Delivery attempts before giving up")
    NOTIFY_DISPATCH_INTERVAL_SECONDS: int = Field(
        default=60, ge=0, description="Background retry of due deliveries; 0 = off (dispatch only on publish / admin)")
    # SMS / phone: off unless a provider is configured. "http" = a provider API reached with
    # SMS_HTTP_URL + SMS_HTTP_TOKEN; "log" = development only (refused in production).
    SMS_PROVIDER: Optional[Literal["http", "log"]] = None
    SMS_HTTP_URL: Optional[str] = None
    SMS_HTTP_TOKEN: Optional[str] = None
    SMS_STATUS_SECRET: Optional[str] = Field(
        default=None, description="HMAC key the provider signs delivery-status callbacks with")
    API_BASE_URL: str = Field(default="http://localhost:8000",
                              description="Public backend URL (SMS delivery-status callbacks)")
    SMS_SENDER_ID: str = "SCHSTU"
    SMS_CONSENT_VERSION: str = "1"

    @field_validator("SMS_PROVIDER", mode="before")
    @classmethod
    def _sms_provider_blank_is_none(cls, v):
        return v or None                 # "SMS_PROVIDER=" in .env means "not configured"

    @property
    def cookie_secure(self) -> bool:
        if self.COOKIE_SECURE is not None:
            return self.COOKIE_SECURE
        return self.ENVIRONMENT == "production"

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
