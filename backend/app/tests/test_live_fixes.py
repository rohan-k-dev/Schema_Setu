"""
Phase 8 fixes found in the first run with real API keys:
- Sarvam Translate rejects input over 1000 chars -> long replies are chunked.
- Reply validator treated bold section headings ("**Schemes that ...**") as invented scheme names.
- LLM prompts were too large for Groq's free-tier tokens-per-minute limit -> compact
  scheme data and shortened assistant history.
"""

import asyncio
import json

from langchain_core.messages import AIMessage, HumanMessage


# ─── translation chunking ─────────────────────────────────────

def test_split_respects_limit_and_keeps_text():
    from app.services.language_service import _split_for_translation, MAX_TRANSLATE_CHARS
    text = "\n".join(["1. Pradhan Mantri Kisan Samman Nidhi gives income support. " * 4] * 12)
    chunks = _split_for_translation(text)
    assert len(chunks) > 1
    assert all(len(c) <= MAX_TRANSLATE_CHARS for c in chunks)
    assert "".join(c.replace("\n", "").replace(" ", "") for c in chunks) == text.replace("\n", "").replace(" ", "")


def test_split_breaks_a_single_long_line():
    from app.services.language_service import _split_for_translation, MAX_TRANSLATE_CHARS
    chunks = _split_for_translation("This is one long sentence. " * 100)
    assert all(len(c) <= MAX_TRANSLATE_CHARS for c in chunks)


def test_long_text_translated_in_chunks(monkeypatch):
    import app.services.language_service as ls
    calls = []

    async def fake_chunk(text, src, tgt):
        calls.append(len(text))
        return text.upper()

    monkeypatch.setattr(ls, "_translate_chunk", fake_chunk)
    text = "\n".join(["Scheme line with some words in it."] * 60)
    out = asyncio.run(ls._translate(text, "en-IN", "kn-IN"))
    assert len(calls) > 1 and max(calls) <= ls.MAX_TRANSLATE_CHARS
    assert out == text.upper()


def test_translation_keeps_line_breaks_and_blank_lines(monkeypatch):
    import app.services.language_service as ls

    async def fake_chunk(text, src, tgt):
        assert "\n" not in text                       # Sarvam would merge lines
        return f"<{text}>"

    monkeypatch.setattr(ls, "_translate_chunk", fake_chunk)
    out = asyncio.run(ls._translate("1. A scheme\n2. B scheme\n\nNote", "en-IN", "hi-IN"))
    assert out == "<1. A scheme>\n<2. B scheme>\n\n<Note>"


# ─── text-to-speech: Sarvam accepts <= 500 chars per input ────

def test_tts_split_respects_limit_and_strips_markdown():
    from app.services.voice_service import split_for_tts, TTS_MAX_CHARS, TTS_MAX_TOTAL_CHARS
    reply = "\n".join(f"{i}. **Scheme {i}** – *Benefit:* Rs. 6,000 per year. # | done" for i in range(60))
    chunks = split_for_tts(reply)
    assert chunks and all(len(c) <= TTS_MAX_CHARS for c in chunks)
    joined = " ".join(chunks)
    assert "*" not in joined and "#" not in joined and "|" not in joined
    assert len(joined) <= TTS_MAX_TOTAL_CHARS + len(chunks)
    assert split_for_tts("word" * 400)                  # no spaces at all still splits
    assert all(len(c) <= TTS_MAX_CHARS for c in split_for_tts("word" * 400))


def test_join_wav_concatenates_clips():
    import base64, io, wave
    from app.services.voice_service import join_wav_base64

    def clip(n):
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(b"\x01\x00" * n)
        return base64.b64encode(buf.getvalue()).decode()

    out = join_wav_base64([clip(100), clip(250)])
    with wave.open(io.BytesIO(base64.b64decode(out)), "rb") as r:
        assert r.getnframes() == 350 and r.getframerate() == 16000


def test_long_tts_text_spoken_in_pieces(monkeypatch):
    import app.services.voice_service as vs
    from app.core.config import settings
    monkeypatch.setattr(settings, "SARVAM_API_KEY", "test")
    sent = []

    async def fake_chunk(text, lang, key):
        sent.append(text)
        return "AUDIO"

    monkeypatch.setattr(vs, "_speak_chunk", fake_chunk)
    monkeypatch.setattr(vs, "join_wav_base64", lambda audios: "+".join(audios))
    out = asyncio.run(vs.generate_speech("Sentence one is here. " * 80, "hi"))
    assert len(sent) > 1 and all(len(t) <= vs.TTS_MAX_CHARS for t in sent)
    assert out == "+".join(["AUDIO"] * len(sent))


# ─── speech-to-text: browser MIME types ───────────────────────

def test_asr_sends_bare_mime_type(monkeypatch):
    """Chrome records 'audio/webm;codecs=opus'; Sarvam rejects the codecs parameter (HTTP 400)."""
    import httpx
    import app.services.voice_service as vs
    from app.core.config import settings
    monkeypatch.setattr(settings, "SARVAM_API_KEY", "test")
    seen = {}

    async def fake_post(self, url, **kwargs):
        seen["type"] = kwargs["files"]["file"][2]
        return httpx.Response(200, json={"transcript": "hello", "language_code": "en-IN"},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    result = asyncio.run(vs.transcribe_audio(b"\x1aE\xdf\xa3" + b"0" * 2000, "rec.webm",
                                             "audio/webm;codecs=opus", "en"))
    assert seen["type"] == "audio/webm"
    assert result and result.text == "hello"


# ─── validator: headings are not scheme names ─────────────────

SCHEMES = [{"scheme_id": "PM_KISAN", "name": "Pradhan Mantri Kisan Samman Nidhi",
            "eligibility_status": "ELIGIBLE", "official_url": "https://pmkisan.gov.in"}]


def test_bold_section_heading_is_not_a_scheme_name():
    from app.xai.response_validator import validate_llm_response
    text = ("**Schemes you may be eligible for**\n- **Pradhan Mantri Kisan Samman Nidhi**: matches.\n"
            "**Schemes that need more information**\n- none")
    ok, reasons = validate_llm_response(text, SCHEMES)
    assert ok, reasons


def test_invented_singular_scheme_still_rejected():
    from app.xai.response_validator import validate_llm_response
    ok, reasons = validate_llm_response("You can also apply for **Kisan Gold Bonus Scheme**.", SCHEMES)
    assert not ok and any("unknown scheme name" in r for r in reasons)


# ─── smaller prompts ──────────────────────────────────────────

def test_compact_scheme_keeps_wording_fields_and_redacts():
    from app.utils.privacy import compact_scheme_for_llm
    card = {"scheme_id": "X", "name": "X Scheme", "eligibility_status": "ELIGIBLE",
            "benefit_summary": "Rs 6000", "documents": ["Aadhaar Card"], "description": "long " * 50,
            "sources": [{"url": "u"}], "graph_evidence": ["e"], "source_references": ["r"],
            "matched_criteria": [{"field": "annual_income", "user_value": 90000, "required_value": 100000,
                                  "operator": "LTE", "source_text": "t" * 200}]}
    c = compact_scheme_for_llm(card)
    assert set(c) <= {"scheme_id", "name", "eligibility_status", "benefit_summary", "documents",
                      "application_steps", "official_url", "missing_information",
                      "matched_criteria", "failed_criteria"}
    assert "description" not in c and "sources" not in c
    assert c["matched_criteria"][0]["user_value"] == "(provided by user)"      # still redacted
    assert len(json.dumps(c)) < len(json.dumps(card)) / 3


def test_recent_history_truncates_only_assistant_messages():
    from app.services.llm_service import recent_history, MAX_ASSISTANT_CHARS_IN_HISTORY
    long_reply = "Scheme list. " * 200
    user_text = "I have 2 acres " * 50
    msgs = [HumanMessage(content=user_text), AIMessage(content=long_reply), ("assistant", long_reply)]
    out = recent_history(msgs, 10)
    assert out[0].content == user_text
    assert len(out[1].content) <= MAX_ASSISTANT_CHARS_IN_HISTORY + 2
    assert len(out[2].content) <= MAX_ASSISTANT_CHARS_IN_HISTORY + 2
    assert len(recent_history(msgs, 2)) == 2


def test_reasoning_effort_only_for_gpt_oss(monkeypatch):
    import app.services.llm_service as llm
    from app.core.config import settings
    monkeypatch.setattr(settings, "GROQ_API_KEY", "test-key")
    for model, expected in (("openai/gpt-oss-20b", {"reasoning_effort": "low"}), ("llama-x", {})):
        monkeypatch.setattr(settings, "GROQ_MODEL", model)
        monkeypatch.setattr(llm, "_llm", None)
        assert llm._get_llm().model_kwargs == expected
    monkeypatch.setattr(llm, "_llm", None)
