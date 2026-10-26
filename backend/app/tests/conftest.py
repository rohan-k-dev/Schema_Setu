"""
Keep the test suite offline and deterministic.

backend/.env may hold real API keys (pydantic-settings reads it when tests run from
backend/). Tests must never call Groq, Tavily or Sarvam, so the keys are blanked for the
whole session; tests that need a key set one explicitly with monkeypatch.
Live checking of official websites (docs/LIVE_VERIFICATION.md) is off too: those tests turn it
on with mocked network transports, so no test ever reaches a real government site.
"""

import pytest

from app.core.config import settings


@pytest.fixture(autouse=True, scope="session")
def _no_live_api_keys():
    saved = {k: getattr(settings, k) for k in ("GROQ_API_KEY", "TAVILY_API_KEY", "SARVAM_API_KEY",
                                                "LIVE_VERIFICATION_ENABLED")}
    for k in saved:
        setattr(settings, k, None if k.endswith("_KEY") else False)
    yield
    for k, v in saved.items():
        setattr(settings, k, v)
