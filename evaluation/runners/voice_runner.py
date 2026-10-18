"""
Voice evaluation with mocked ASR/TTS (Phase 7 §62–§72, §109).

Measures voice plumbing and post-ASR handling. Transcription accuracy / WER
require real audio and are NOT measured offline.
"""

import base64
from typing import Any, Dict, List

from evaluation.metrics import summarize_checks
from evaluation.runners.common import (
    load_dataset, check, new_thread, get_client, value_matches, make_wav,
)
from evaluation.runners.e2e_runner import build_mocks, send_turn
from evaluation.fixtures.mock_services import (
    offline_environment, ScriptedProfileLLM, FakeTranslator, FakeVoice, FakeWebSearch,
)


def _voice_post(client, audio: bytes, content_type: str, language="en", filename="recording.wav"):
    r = client.post("/voice", files={"file": (filename, audio, content_type)},
                    data={"thread_id": new_thread("vf"), "language": language})
    return r.status_code, r.json()


def run(corpus_db) -> Dict[str, Any]:
    ds = load_dataset("voice_cases.json")
    client = get_client()

    # ── pipeline: audio → ASR → translation → same LangGraph → profile (§62, §65) ──
    pipeline_checks = []
    field_total = field_ok = 0
    for case in ds["pipeline_cases"]:
        turn = {"channel": "voice", **case}
        script, translator, voice = build_mocks([turn])
        thread = new_thread(case["case_id"])
        with offline_environment(db=corpus_db, profile_llm=script, translator=translator, voice=voice,
                                 web=FakeWebSearch([])):
            code, body = send_turn(client, thread, turn)
        prof = body.get("current_profile") or {}
        failures = []
        if code != 200 or body.get("status") == "error":
            failures.append(f"HTTP {code} status={body.get('status')}")
        if body.get("user_transcript") != case["transcript"]:
            failures.append("transcript not returned to the user")
        for f, v in case["expected_profile"].items():
            field_total += 1
            if value_matches(prof.get(f), v):
                field_ok += 1
            else:
                failures.append(f"{f}={prof.get(f)!r} expected {v!r}")
        pipeline_checks.append(check(case["case_id"], not failures, language=case["language"],
                                     failures=failures))

    # ── session continuity / mixed modality (§70, §71) ────────────
    session_checks = []
    for case in ds["session_cases"]:
        script, translator, voice = build_mocks(case["turns"])
        thread = new_thread(case["case_id"])
        body = {}
        with offline_environment(db=corpus_db, profile_llm=script, translator=translator, voice=voice,
                                 web=FakeWebSearch([])):
            for t in case["turns"]:
                _, body = send_turn(client, thread, t)
        prof = body.get("current_profile") or {}
        failures = [f"{f}={prof.get(f)!r} expected {v!r}" for f, v in case["expect_profile"].items()
                    if not value_matches(prof.get(f), v)]
        if body.get("status") not in case["expect_status_in"]:
            failures.append(f"status={body.get('status')}")
        session_checks.append(check(case["case_id"], not failures, failures=failures))

    # ── failures and upload security (§66–§69, §109) ──────────────
    failure_checks = []
    wav = make_wav("vf-probe")
    for case in ds["failure_cases"]:
        kind = case["kind"]
        ok, details = False, {}
        if kind == "asr_failure":
            with offline_environment(db=corpus_db, voice=FakeVoice(asr_fail=True)):
                code, body = _voice_post(client, wav, "audio/wav")
            ok = code == 200 and body.get("status") == "error" and "text" in (body.get("reply") or "").lower()
            details = {"status": body.get("status"), "reply": body.get("reply")}
        elif kind == "asr_empty":
            with offline_environment(db=corpus_db, voice=FakeVoice({})):
                code, body = _voice_post(client, wav, "audio/wav")
            ok = (body.get("error") or {}).get("code") == "VOICE_TRANSCRIPTION_FAILED"
            details = {"error": body.get("error")}
        elif kind == "tts_failure":
            with offline_environment(db=corpus_db, voice=FakeVoice(tts_fail=True)):
                r = client.post("/tts", json={"text": "Your schemes are ready.", "language_code": "hi"})
            body = r.json()
            ok = r.status_code == 200 and not body.get("audio_base64") and bool(body.get("error"))
            details = {"error": body.get("error")}
        elif kind == "translation_failure":
            fv = FakeVoice({wav: "मैं कर्नाटक से हूँ"})
            with offline_environment(db=corpus_db, voice=fv, translator=FakeTranslator(fail="fail_both")):
                code, body = _voice_post(client, wav, "audio/wav", language="hi")
            ok = code == 200 and body.get("status") != "error"
            details = {"status": body.get("status")}
        elif kind in ("empty_audio", "oversized_audio", "wrong_mime", "malformed_audio"):
            fv = FakeVoice({})
            payload = {"empty_audio": b"",
                       "oversized_audio": b"RIFF" + b"\x00" * (11 * 1024 * 1024),
                       "wrong_mime": wav,
                       "malformed_audio": (case.get("payload") or "").encode()}[kind]
            ctype = case.get("content_type", "audio/wav")
            with offline_environment(db=corpus_db, voice=fv):
                code, body = _voice_post(client, payload, ctype)
            ok = (body.get("error") or {}).get("code") == "VALIDATION_ERROR" and fv.asr_calls == 0
            details = {"error": (body.get("error") or {}).get("code"), "asr_calls": fv.asr_calls}
        elif kind == "suspicious_filename":
            fv = FakeVoice({wav: "I am from Karnataka"})
            script = ScriptedProfileLLM({"I am from Karnataka": {"state": "Karnataka"}})
            with offline_environment(db=corpus_db, voice=fv, profile_llm=script):
                code, body = _voice_post(client, wav, "audio/wav", filename=case["filename"])
            ok = code == 200 and fv.asr_filenames and all(".." not in f and "/" not in f for f in fv.asr_filenames)
            details = {"asr_filenames": fv.asr_filenames}
        elif kind == "tts_valid_audio":
            with offline_environment(db=corpus_db, voice=FakeVoice()):
                r = client.post("/tts", json={"text": "Namaste", "language_code": "hi"})
            audio = r.json().get("audio_base64") or ""
            try:
                ok = len(base64.b64decode(audio, validate=True)) > 0
            except Exception:
                ok = False
        failure_checks.append(check(case["case_id"], ok, kind=kind, **details))

    return {
        "cases": len(ds["pipeline_cases"]) + len(ds["session_cases"]) + len(ds["failure_cases"]),
        "post_asr_pipeline": summarize_checks(pipeline_checks),
        "voice_field_extraction": {"fields": field_total, "correct": field_ok,
                                   "accuracy": round(field_ok / field_total, 4) if field_total else None,
                                   "note": "Given mocked ASR transcripts; not ASR accuracy."},
        "session_continuity": summarize_checks(session_checks),
        "failures_and_upload_security": summarize_checks(failure_checks),
        "wer": ds["wer_status"],
    }
