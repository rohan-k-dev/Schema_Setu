"""
Mocked external services for offline evaluation.

Every external dependency (Groq LLM, Tavily, Sarvam ASR / TTS / Translate)
is replaced by a deterministic fake so the evaluation is reproducible on a
clean machine with no API keys.

IMPORTANT — what offline mode does NOT measure:
  The scripted profile LLM returns the human-curated extraction for each
  utterance. Offline E2E therefore measures everything AFTER extraction
  (merge, completeness, retrieval, eligibility, XAI, ranking, formatting,
  translation plumbing, review escalation) — not the LLM's extraction accuracy.
  LLM extraction accuracy is measured only in --live mode.
"""

import asyncio
import contextlib
from typing import Any, Callable, Dict, List, Optional

from langchain_core.runnables import RunnableLambda


class ScriptedProfileLLM:
    """
    Fake structured-output LLM for profile extraction.

    script: {utterance (internal English) -> extraction dict}
    Unknown utterances extract nothing (an empty profile), which is the
    correct behaviour for an utterance carrying no profile facts.
    """

    def __init__(self, script: Optional[Dict[str, Dict[str, Any]]] = None):
        self.script: Dict[str, Dict[str, Any]] = dict(script or {})
        self.calls: List[str] = []

    def add(self, utterance: str, extraction: Dict[str, Any]) -> None:
        self.script[utterance] = extraction

    def _invoke(self, prompt_value):
        from app.models.profile import FarmerProfile
        messages = prompt_value.to_messages()
        latest = ""
        for m in reversed(messages):
            if getattr(m, "type", "") == "human":
                latest = m.content
                break
        self.calls.append(latest)
        return FarmerProfile(**self.script.get(latest, {}))

    def runnable(self):
        return RunnableLambda(self._invoke)


class ScriptedTextLLM:
    """
    Fake chat LLM used by the query rewriter / response formatter / question agent.

    mode:
      "unavailable" — raises (simulates Groq outage → deterministic fallbacks)
      "fixed"       — always returns `text`
      "callable"    — returns fn(prompt_value)
    """

    def __init__(self, mode: str = "unavailable", text: str = "", fn: Optional[Callable] = None):
        self.mode = mode
        self.text = text
        self.fn = fn
        self.calls = 0
        self.prompts: List[str] = []

    def _invoke(self, prompt_value):
        self.calls += 1
        try:
            self.prompts.append(prompt_value.to_string())
        except Exception:
            self.prompts.append(str(prompt_value))
        if self.mode == "unavailable":
            raise ConnectionError("Simulated LLM outage (evaluation fixture)")
        if self.mode == "callable" and self.fn:
            return self.fn(prompt_value)
        return self.text

    def runnable(self):
        return RunnableLambda(self._invoke)


class FakeWebSearch:
    """
    Fake Tavily search. results: list of raw Tavily-shaped dicts
    ({"title", "url", "content"}); fail=True raises; delay_s sleeps.

    The fake returns raw Tavily records; app.services.search_service is
    patched at the Tavily-client level so its own mapping logic is exercised.
    """

    def __init__(self, results: Optional[List[Dict[str, Any]]] = None,
                 fail: bool = False, delay_s: float = 0.0):
        self.results = list(results or [])
        self.fail = fail
        self.delay_s = delay_s
        self.queries: List[str] = []

    def search(self, query: str, search_depth: str = "advanced", max_results: int = 5, **_):
        import time
        self.queries.append(query)
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.fail:
            raise ConnectionError("Simulated Tavily outage (evaluation fixture)")
        return {"results": self.results[:max_results]}


class FakeTranslator:
    """
    Fake Sarvam translate. table: {text -> translation}.
    Untranslatable text is returned unchanged.
    fail: "" (never), "fail_both", "fail_inbound" (to English), "fail_outbound" (from English).
    """

    def __init__(self, table: Optional[Dict[str, str]] = None, fail: str = ""):
        self.table = dict(table or {})
        self.fail = fail
        self.calls: List[Dict[str, str]] = []

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        self.calls.append({"text": text, "source": source_lang, "target": target_lang})
        inbound = target_lang == "en-IN"
        if (self.fail == "fail_both"
                or (self.fail == "fail_inbound" and inbound)
                or (self.fail == "fail_outbound" and not inbound)):
            from app.core.exceptions import ExternalServiceError
            raise ExternalServiceError("Sarvam Translate", "Simulated outage (evaluation fixture)")
        return self.table.get(text, text)


class FakeVoice:
    """Fake Sarvam ASR + TTS."""

    def __init__(self, transcripts: Optional[Dict[bytes, str]] = None,
                 asr_fail: bool = False, tts_fail: bool = False, tts_audio: str = "UklGRgAAAABXQVZF"):
        self.transcripts = dict(transcripts or {})
        self.asr_fail = asr_fail
        self.tts_fail = tts_fail
        self.tts_audio = tts_audio
        self.asr_calls = 0
        self.tts_calls = 0
        self.asr_filenames: List[str] = []

    async def transcribe_audio(self, audio_bytes: bytes, filename: str, content_type: str,
                               language_code: str = ""):
        from app.services.voice_service import ASRResult
        from app.core.exceptions import ExternalServiceError
        self.asr_calls += 1
        self.asr_filenames.append(filename)
        if self.asr_fail:
            raise ExternalServiceError("Sarvam ASR", "Simulated outage (evaluation fixture)")
        text = self.transcripts.get(audio_bytes)
        if not text:
            return None
        return ASRResult(text=text, language=language_code)

    async def generate_speech(self, text: str, language_code: str = "hi-IN"):
        from app.core.exceptions import ExternalServiceError
        self.tts_calls += 1
        if self.tts_fail:
            raise ExternalServiceError("Sarvam TTS", "Simulated outage (evaluation fixture)")
        return self.tts_audio if text else None


@contextlib.contextmanager
def offline_environment(
    db=None,
    profile_llm: Optional[ScriptedProfileLLM] = None,
    text_llm: Optional[ScriptedTextLLM] = None,
    web: Optional[FakeWebSearch] = None,
    translator: Optional[FakeTranslator] = None,
    voice: Optional[FakeVoice] = None,
    graph_available: bool = True,
):
    """
    Patch every external dependency for one evaluation block.

    db: CorpusDB (or None → real repositories, which fail without PostgreSQL)
    graph_available: False simulates a Knowledge Graph outage.
    """
    import app.services.llm_service as llm_service
    import app.services.search_service as search_service
    import app.services.language_service as language_service
    import app.services.knowledge_graph_service as kg_service
    import app.api.voice as voice_api
    from evaluation.fixtures.corpus_db import patched_repositories

    profile_llm = profile_llm or ScriptedProfileLLM()
    text_llm = text_llm or ScriptedTextLLM("unavailable")
    web = web or FakeWebSearch()
    translator = translator or FakeTranslator()
    voice = voice or FakeVoice()

    saved = {
        "structured": llm_service._get_structured_llm,
        "llm": llm_service._get_llm,
        "tavily": search_service._get_tavily_client,
        "translate": language_service._translate,
        "asr": voice_api.transcribe_audio,
        "tts": voice_api.generate_speech,
        "graph_available": kg_service._graph_available,
    }

    llm_service._get_structured_llm = lambda: profile_llm.runnable()
    llm_service._get_llm = lambda: text_llm.runnable()
    search_service._get_tavily_client = lambda: web
    language_service._translate = translator.translate
    voice_api.transcribe_audio = voice.transcribe_audio
    voice_api.generate_speech = voice.generate_speech

    if graph_available:
        if kg_service.get_graph_repo() is None:
            kg_service.init_knowledge_graph()
    else:
        kg_service._graph_available = False

    stack = contextlib.ExitStack()
    try:
        if db is not None:
            stack.enter_context(patched_repositories(db))
        yield {"profile_llm": profile_llm, "text_llm": text_llm, "web": web,
               "translator": translator, "voice": voice, "db": db}
    finally:
        stack.close()
        llm_service._get_structured_llm = saved["structured"]
        llm_service._get_llm = saved["llm"]
        search_service._get_tavily_client = saved["tavily"]
        language_service._translate = saved["translate"]
        voice_api.transcribe_audio = saved["asr"]
        voice_api.generate_speech = saved["tts"]
        kg_service._graph_available = kg_service.get_graph_repo() is not None


def run(coro):
    """Run a coroutine from synchronous runner code."""
    return asyncio.run(coro)
