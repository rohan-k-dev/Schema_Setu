from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_optional_farmer_id
from app.main import app
from app.models.auth_schemas import ProfileResponse
from app.services.chat_profile_service import (
    load_saved_chat_profile,
    merge_chat_profiles,
    save_chat_profile,
)


def test_merge_chat_profile_fills_missing_fields_without_overwriting_chat():
    merged = merge_chat_profiles(
        {"state": "Maharashtra", "primary_crop": None},
        {"state": "Karnataka", "primary_crop": "rice", "age": 42},
    )

    assert merged == {
        "state": "Maharashtra",
        "primary_crop": "rice",
        "age": 42,
    }


@pytest.mark.asyncio
async def test_load_saved_profile_returns_empty_for_anonymous_chat():
    assert await load_saved_chat_profile(None) == ({}, False)


@pytest.mark.asyncio
async def test_save_chat_profile_requires_explicit_or_existing_consent():
    with patch(
        "app.services.chat_profile_service.update_profile",
        new_callable=AsyncMock,
    ) as update:
        saved = await save_chat_profile(
            "farmer-id",
            {"state": "Karnataka"},
            consent_to_save=False,
            existing_consent=False,
        )

    assert saved is False
    update.assert_not_awaited()


@pytest.mark.asyncio
async def test_save_chat_profile_persists_extracted_details_with_explicit_consent():
    profile_response = ProfileResponse(
        farmer_id="farmer-id",
        full_name=None,
        email="farmer@example.com",
        state="Karnataka",
        district=None,
        land_size=2.5,
        land_unit="acre",
        land_size_acres=2.5,
        primary_crop="maize",
        other_crops=None,
        farming_type=None,
        occupation=None,
        age=None,
        gender=None,
        category=None,
        income_range=None,
        residence=None,
        consent_given=True,
        consent_given_at=None,
        profile_completeness=30,
        version=1,
        updated_at=None,
    )
    with patch(
        "app.services.chat_profile_service.update_profile",
        new_callable=AsyncMock,
        return_value=profile_response,
    ) as update:
        saved = await save_chat_profile(
            "farmer-id",
            {"state": "Karnataka", "land_size_acres": 2.5, "primary_crop": "maize"},
            consent_to_save=True,
            existing_consent=False,
        )

    assert saved is True
    request = update.await_args.args[1]
    assert request.state == "Karnataka"
    assert request.land_size == 2.5 and request.land_unit == "acre"
    assert request.primary_crop == "maize"
    assert request.consent_given is True


def test_authenticated_chat_starts_with_saved_profile():
    saved = {
        "state": "Karnataka",
        "land_size_acres": 2.5,
        "primary_crop": "maize",
    }
    final_state = {
        "messages": [],
        "profile": saved,
        "response_status": "asking_question",
        "response_text": "What is your occupation?",
        "response_schemes": [],
    }
    graph = SimpleNamespace(
        aget_state=AsyncMock(return_value=SimpleNamespace(values={})),
        ainvoke=AsyncMock(return_value=final_state),
    )
    client = TestClient(app)
    with (
        patch(
            "app.api.chat.translate_to_internal",
            new_callable=AsyncMock,
            side_effect=lambda message, _language: message,
        ),
        patch(
            "app.api.chat.load_saved_chat_profile",
            new_callable=AsyncMock,
            return_value=(saved, True),
        ),
        patch(
            "app.api.chat.save_chat_profile",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.api.chat.kisan_agent",
            graph,
        ),
    ):
        app.dependency_overrides[get_optional_farmer_id] = lambda: "farmer-id"
        try:
            response = client.post(
                "/chat",
                json={"message": "Find schemes for me", "thread_id": "profile-seed-test"},
            )
        finally:
            app.dependency_overrides.pop(get_optional_farmer_id, None)

    assert response.status_code == 200
    assert graph.ainvoke.await_args.args[0]["profile"] == saved
    assert response.json()["profile_saved"] is True
