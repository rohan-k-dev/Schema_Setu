"""
Tests for API health endpoints.

Uses FastAPI TestClient — no real database or API keys needed.

Phase 7 (BUG-001): these tests used to be skipped when `app.main` failed to
import, which hid a broken environment. A failed import now fails the suite.
"""

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


class TestHealthEndpoints:
    """Test health check endpoints."""

    def test_root_endpoint(self):
        """GET / should return API status."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "SchemeSetu" in data["message"]

    def test_liveness_endpoint(self):
        """GET /health/live should always return alive."""
        response = client.get("/health/live")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "alive"

    def test_health_endpoint(self):
        """GET /health should return status info."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "db_connected" in data

    def test_readiness_endpoint(self):
        """GET /health/ready should return dependency status."""
        response = client.get("/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "db_ready" in data
        assert "groq_configured" in data
        assert "tavily_configured" in data
        assert "sarvam_configured" in data
