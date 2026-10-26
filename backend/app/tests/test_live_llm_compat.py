"""
Phase 8 (first live run): compatibility with the real Groq structured output.

- with_structured_output() returns a plain dict for the pydantic-v2 FarmerProfile with
  this langchain version; the profile agent must accept it (it called .model_dump() on it).
- The Groq model is configurable (llama-3.3-70b-versatile was no longer offered).
"""

import asyncio

from langchain_core.runnables import RunnableLambda


def test_profile_agent_accepts_dict_extraction(monkeypatch):
    import app.services.llm_service as llm
    from app.agents.profile_agent import profile_agent_node
    monkeypatch.setattr(llm, "_get_structured_llm", lambda: RunnableLambda(lambda _: {
        "state": "karnataka", "land_size_acres": 2, "primary_crop": "Ragi",
        "occupation": "farmer", "unknown_extra_key": "ignored"}))
    out = asyncio.run(profile_agent_node({"messages": [("human", "I farm ragi on 2 acres in Karnataka")]}))
    profile = out["profile"]
    assert out.get("error") is None
    assert profile["state"] == "Karnataka"            # canonicalised by FarmerProfile
    assert profile["land_size_acres"] == 2
    assert profile["primary_crop"] == "ragi"


def test_profile_agent_dict_with_invalid_values_keeps_them_unknown(monkeypatch):
    import app.services.llm_service as llm
    from app.agents.profile_agent import profile_agent_node
    monkeypatch.setattr(llm, "_get_structured_llm", lambda: RunnableLambda(lambda _: {
        "state": "Xyzland", "land_size_acres": -3}))
    out = asyncio.run(profile_agent_node({"messages": [("human", "x")]}))
    profile = out["profile"] or {}
    assert profile.get("state") is None
    assert profile.get("land_size_acres") is None


def test_groq_model_is_configurable(monkeypatch):
    import app.services.llm_service as llm
    from app.core.config import settings
    monkeypatch.setattr(settings, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(settings, "GROQ_MODEL", "some/model-id")
    monkeypatch.setattr(llm, "_llm", None)
    assert llm._get_llm().model_name == "some/model-id"
    monkeypatch.setattr(llm, "_llm", None)
