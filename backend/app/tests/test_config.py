"""
Tests for configuration and exceptions.
"""

import pytest
from app.core.config import Settings
from app.core.exceptions import (
    SchemSetuError,
    ConfigurationError,
    ExternalServiceError,
    DatabaseError,
    ValidationError,
    GraphExecutionError,
)


class TestConfiguration:
    """Test configuration loading behavior."""

    def test_default_settings(self):
        """Settings should load with safe defaults even without .env."""
        s = Settings(
            _env_file=None,  # Don't load any .env
        )
        # API keys should be None (not crash)
        assert s.GROQ_API_KEY is None
        assert s.TAVILY_API_KEY is None
        assert s.SARVAM_API_KEY is None
        assert s.NEON_DATABASE_URL is None
        # Defaults should be set
        assert s.BACKEND_PORT == 8000
        assert s.ENVIRONMENT == "development"
        assert s.LOG_LEVEL == "INFO"

    def test_cors_default_is_local_frontend(self):
        """CORS defaults to the local frontend origin only."""
        s = Settings(_env_file=None)
        assert s.CORS_ORIGINS == ["http://localhost:3000"]


class TestExceptions:
    """Test custom exception hierarchy."""

    def test_base_error(self):
        err = SchemSetuError("test error")
        assert err.message == "test error"
        assert err.code == "INTERNAL_ERROR"

    def test_configuration_error(self):
        err = ConfigurationError("Missing key")
        assert err.code == "CONFIGURATION_ERROR"

    def test_external_service_error(self):
        err = ExternalServiceError("Groq", "API timeout")
        assert "Groq" in err.message
        assert err.service == "Groq"
        assert err.code == "EXTERNAL_SERVICE_ERROR"

    def test_database_error(self):
        err = DatabaseError("Connection lost")
        assert err.code == "DATABASE_ERROR"

    def test_graph_execution_error(self):
        err = GraphExecutionError()
        assert err.code == "GRAPH_EXECUTION_ERROR"
