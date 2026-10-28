"""
Application-specific exceptions.

These provide structured error handling throughout the codebase.
FastAPI exception handlers translate these into safe API responses.
"""


class SchemSetuError(Exception):
    """Base exception for the SchemeSetu application."""

    def __init__(self, message: str = "An internal error occurred.", code: str = "INTERNAL_ERROR"):
        self.message = message
        self.code = code
        super().__init__(self.message)


class ConfigurationError(SchemSetuError):
    """Raised when a required configuration value is missing or invalid."""

    def __init__(self, message: str = "A required configuration is missing."):
        super().__init__(message=message, code="CONFIGURATION_ERROR")


class ExternalServiceError(SchemSetuError):
    """Raised when an external API call (Groq, Tavily, Sarvam) fails."""

    def __init__(self, service: str, message: str = "External service request failed."):
        self.service = service
        super().__init__(message=f"{service}: {message}", code="EXTERNAL_SERVICE_ERROR")


class ServiceQuotaError(ExternalServiceError):
    """The provider refused for billing reasons (no credits / quota used up) — retrying won't help."""

    def __init__(self, service: str):
        super().__init__(service, "The service account has no credits left (quota exhausted).")
        self.code = "SERVICE_QUOTA_EXHAUSTED"


def raise_for_provider_status(service: str, response) -> None:
    """HTTP 402, or 429 with a quota / credits error, means the account is out of credits."""
    body = (getattr(response, "text", "") or "").lower()
    if response.status_code == 402 or (response.status_code == 429 and ("quota" in body or "credit" in body)):
        raise ServiceQuotaError(service)


class DatabaseError(SchemSetuError):
    """Raised when a database operation fails."""

    def __init__(self, message: str = "Database operation failed."):
        super().__init__(message=message, code="DATABASE_ERROR")


class ValidationError(SchemSetuError):
    """Raised when request validation fails beyond Pydantic's checks."""

    def __init__(self, message: str = "Request validation failed."):
        super().__init__(message=message, code="VALIDATION_ERROR")


class GraphExecutionError(SchemSetuError):
    """Raised when the LangGraph workflow encounters an error."""

    def __init__(self, message: str = "Agent workflow execution failed."):
        super().__init__(message=message, code="GRAPH_EXECUTION_ERROR")


def public_message(error: SchemSetuError) -> str:
    """
    Message that is safe to return to API clients (Phase 8).

    Configuration errors name environment variables and files; clients only
    learn that the service is not configured. Full detail stays in server logs.
    Database errors may carry driver text and are likewise replaced.
    """
    if isinstance(error, ConfigurationError):
        return "This service is not configured on the server."
    if isinstance(error, DatabaseError):
        return "The scheme database is temporarily unavailable."
    return error.message


LANGUAGE_SERVICE_UNAVAILABLE = "LANGUAGE_SERVICE_UNAVAILABLE"
