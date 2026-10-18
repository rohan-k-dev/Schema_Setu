"""
SchemeSetu DEMO MODE server (Phase 8 Step 29).

Runs the real FastAPI app and the real LangGraph pipeline, retrieval,
Knowledge Graph, eligibility engine, XAI and human-review queue, with the real
PostgreSQL database when DATABASE_URL is set (otherwise the corpus fixture).

Only the services that need API keys are replaced, deterministically:
  - LLM language understanding → scripted extraction for the utterances in
    evaluation/datasets/demo_scenarios.json (other text extracts nothing)
  - LLM reply wording          → unavailable → deterministic evidence-based replies
  - Sarvam translation         → lookup table from the demo script
  - Sarvam ASR                 → returns the demo script's voice transcripts in order
  - Sarvam TTS                 → a short tone (so playback can be shown)
  - Tavily live web search     → off (returns no results)

/health reports environment "demo" and the frontend shows a demo banner.
Production behaviour is unchanged: demo mode exists only when this script runs.

Usage (from Scheme_Setu/):
    python scripts/demo_server.py [--port 8000]
"""

import argparse
import base64
import io
import json
import math
import os
import struct
import sys
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import evaluation  # noqa: E402,F401  (backend import path)
from app.database.connection import use_selector_event_loop_on_windows  # noqa: E402
from evaluation import DATASETS_DIR  # noqa: E402
from evaluation.fixtures.mock_services import (  # noqa: E402
    offline_environment, ScriptedProfileLLM, ScriptedTextLLM, FakeTranslator, FakeWebSearch,
)


def _tone_wav_base64(seconds: float = 0.6, freq: int = 660) -> str:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        frames = b"".join(struct.pack("<h", int(6000 * math.sin(2 * math.pi * freq * i / 16000)))
                          for i in range(int(16000 * seconds)))
        w.writeframes(frames)
    return base64.b64encode(buf.getvalue()).decode()


class DemoVoice:
    """Simulated Sarvam ASR/TTS for the demo: any valid recording → next scripted transcript."""

    def __init__(self, transcripts):
        self.transcripts = list(transcripts)
        self.index = 0
        self.tone = _tone_wav_base64()

    async def transcribe_audio(self, audio_bytes, filename, content_type, language_code=""):
        from app.services.voice_service import ASRResult
        if not self.transcripts:
            return None
        text = self.transcripts[self.index % len(self.transcripts)]
        self.index += 1
        return ASRResult(text=text, language=language_code)

    async def generate_speech(self, text, language_code="hi-IN"):
        return self.tone if text else None


def build_demo_mocks():
    with open(os.path.join(DATASETS_DIR, "demo_scenarios.json"), encoding="utf-8") as f:
        cases = json.load(f)["cases"]
    script, table, transcripts = ScriptedProfileLLM(), {}, []
    for case in cases:
        for t in case["turns"]:
            english = t.get("translation") or t.get("input") or t.get("transcript")
            script.add(english, t.get("extraction", {}))
            if t.get("translation"):
                table[t.get("input") or t.get("transcript")] = t["translation"]
            if t.get("channel") == "voice":
                transcripts.append(t["transcript"])
    return script, FakeTranslator(table), DemoVoice(transcripts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    from app.core.config import settings
    settings.ENVIRONMENT = "demo"
    if not settings.REVIEW_API_KEY:
        import secrets
        settings.REVIEW_API_KEY = secrets.token_urlsafe(16)  # per-run key, printed below
    db = None
    if not settings.effective_database_url:
        from evaluation.fixtures.corpus_db import CorpusDB
        db = CorpusDB()
    script, translator, voice = build_demo_mocks()

    print("=" * 70)
    print("SchemeSetu DEMO MODE — external AI services simulated (see docstring)")
    print(f"  database : {'PostgreSQL (DATABASE_URL)' if db is None else 'corpus fixture (no DATABASE_URL)'}")
    print(f"  reviewer : X-Review-Key: {settings.REVIEW_API_KEY}")
    print(f"  script   : {len(script.script)} scripted utterances, {len(voice.transcripts)} voice transcripts")
    print("=" * 70)

    use_selector_event_loop_on_windows()
    import uvicorn
    with offline_environment(db=db, profile_llm=script, text_llm=ScriptedTextLLM("unavailable"),
                             web=FakeWebSearch([]), translator=translator, voice=voice):
        uvicorn.run("app.main:app", host=args.host, port=args.port, loop="asyncio")


if __name__ == "__main__":
    main()
