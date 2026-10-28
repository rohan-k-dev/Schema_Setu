"""
A provider account out of credits (Sarvam answered HTTP 402 "No credits available" on 2026-10-26) is
reported as such — to the farmer in plain words, to clients with its own error code — instead of a
generic "voice processing failed".
"""

from __future__ import annotations

import httpx
import pytest

from app.core.exceptions import ExternalServiceError, ServiceQuotaError, raise_for_provider_status


def resp(status, body=""):
    return httpx.Response(status, text=body, request=httpx.Request("POST", "https://api.sarvam.ai/x"))


@pytest.mark.parametrize("status,body,quota", [
    (402, '{"error":{"message":"No credits available.","code":"insufficient_quota_error"}}', True),
    (429, '{"error":{"code":"insufficient_quota_error"}}', True),
    (429, '{"error":"too many requests"}', False),          # plain rate limit: retrying can help
    (500, "server error", False),
    (403, "forbidden", False),
])
def test_quota_detection(status, body, quota):
    if quota:
        with pytest.raises(ServiceQuotaError) as e:
            raise_for_provider_status("Sarvam ASR", resp(status, body))
        assert e.value.code == "SERVICE_QUOTA_EXHAUSTED" and isinstance(e.value, ExternalServiceError)
    else:
        raise_for_provider_status("Sarvam ASR", resp(status, body))   # no exception


def test_voice_endpoint_says_credits_are_exhausted(monkeypatch):
    from fastapi.testclient import TestClient
    import app.api.voice as voice_api
    from app.main import app

    async def no_credits(*a, **k):
        raise ServiceQuotaError("Sarvam ASR")
    monkeypatch.setattr(voice_api, "transcribe_audio", no_credits, raising=False)
    for name in dir(voice_api):                       # whichever name the endpoint uses for speech-to-text
        if "transcrib" in name.lower() and callable(getattr(voice_api, name)):
            monkeypatch.setattr(voice_api, name, no_credits)
    r = TestClient(app).post("/voice", files={"file": ("a.webm", b"\x1aE\xdf\xa3" + b"0" * 2000, "audio/webm")},
                             data={"thread_id": "t-quota", "language": "en"})
    body = r.json()
    assert body["status"] == "error" and body["error"]["code"] == "SERVICE_QUOTA_EXHAUSTED"
    assert "no credits left" in body["reply"] and "type your question" in body["reply"]
