"""
Reply in the language the farmer uses (reported 2026-10-27: asked in Hindi, heard English).

Typed text: the script decides (Devanagari → Hindi, Kannada script → Kannada …); Latin text keeps the
picker's language. Voice: the language Sarvam detected. The reply is translated into it and the
response says which language it is, so the UI speaks it in that language.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.localization.detect import detect_text_language, spoken_language


@pytest.mark.parametrize("text,selected,expected", [
    ("मैं बिहार का किसान हूँ, मेरे लिए कौन सी योजनाएँ हैं?", "en", "hi"),
    ("मी महाराष्ट्रातील शेतकरी आहे", "mr", "mr"),             # Devanagari + Marathi selected
    ("ನಾನು ಕರ್ನಾಟಕದ ರೈತ", "en", "kn"),
    ("நான் ஒரு விவசாயி", "hi", "ta"),
    ("ਮੈਂ ਕਿਸਾਨ ਹਾਂ", "en", "pa"),
    ("আমি একজন কৃষক", "en", "bn"),
    ("PM Kisan के बारे में बताओ", "en", "hi"),                 # mixed, mostly Hindi
    ("I am a farmer in Bihar", "en", "en"),
    ("mujhe yojana batao", "hi", "hi"),                        # romanised Hindi keeps the picker
    ("", "kn", "kn"),
])
def test_typed_language(text, selected, expected):
    assert detect_text_language(text, selected) == expected


@pytest.mark.parametrize("detected,selected,expected", [
    ("hi-IN", "en", "hi"), ("kn-IN", "hi", "kn"), ("en-IN", "hi", "en"),
    (None, "ta", "ta"), ("", "en", "en"), ("xx-YY", "mr", "mr"),
])
def test_spoken_language(detected, selected, expected):
    assert spoken_language(detected, selected) == expected


class FakeAgent:
    def __init__(self):
        self.seen = []

    async def aget_state(self, config):
        return SimpleNamespace(values={})

    async def ainvoke(self, inputs, config=None):
        self.seen.append(inputs["messages"][0].content)
        return {"messages": [], "response_status": "asking_question", "response_text": "Which crop do you grow?",
                "profile": {}}


@pytest.fixture
def fakes(monkeypatch):
    import app.api.chat as chat_api
    import app.api.voice as voice_api
    agent, calls = FakeAgent(), {"to_internal": [], "from_internal": []}

    async def to_internal(text, lang):
        calls["to_internal"].append(lang)
        return "I am a farmer from Bihar" if lang != "en" else text

    async def from_internal(text, lang):
        calls["from_internal"].append(lang)
        return f"[{lang}] {text}"
    for mod in (chat_api, voice_api):
        monkeypatch.setattr(mod, "kisan_agent", agent)
        monkeypatch.setattr(mod, "translate_to_internal", to_internal)
        monkeypatch.setattr(mod, "translate_from_internal", from_internal)
    return agent, calls


def test_chat_replies_in_hindi_although_picker_is_english(fakes):
    from app.main import app
    agent, calls = fakes
    r = TestClient(app).post("/chat", json={"message": "मैं बिहार का किसान हूँ", "thread_id": "t-hi", "language": "en"})
    d = r.json()
    assert d["language"] == "hi" and d["reply"].startswith("[hi] ")
    assert calls["to_internal"] == ["hi"] and calls["from_internal"] == ["hi"]
    assert agent.seen == ["I am a farmer from Bihar"]                  # pipeline works on English


def test_chat_english_stays_english(fakes):
    from app.main import app
    _, calls = fakes
    d = TestClient(app).post("/chat", json={"message": "I grow maize", "thread_id": "t-en",
                                            "language": "en"}).json()
    assert d["language"] == "en" and d["reply"] == "Which crop do you grow?" and calls["from_internal"] == []


def test_voice_replies_in_the_spoken_language(fakes, monkeypatch):
    import app.api.voice as voice_api
    from app.main import app
    from app.services.voice_service import ASRResult
    agent, calls = fakes

    async def heard_hindi(**kw):
        return ASRResult(text="I am a farmer from Bihar. Which schemes can I get?", language="hi-IN")
    monkeypatch.setattr(voice_api, "transcribe_audio", heard_hindi)
    r = TestClient(app).post("/voice", files={"file": ("a.webm", b"\x1aE\xdf\xa3" + b"0" * 2000, "audio/webm")},
                             data={"thread_id": "t-voice", "language": "en"})
    d = r.json()
    assert d["language"] == "hi" and d["reply"].startswith("[hi] ")
    assert calls["to_internal"] == []                                  # Sarvam already returned English
    assert agent.seen == ["I am a farmer from Bihar. Which schemes can I get?"]
