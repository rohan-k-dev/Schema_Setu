"""
SchemeSetu smoke test (Phase 7 §166, §192–§194).

Modes:
    python scripts/smoke_test.py --base-url http://localhost:8000
        Runs against a deployed/running backend with its real services.
        Voice/TTS checks run only when the server reports Sarvam as configured;
        review checks run only when REVIEW_API_KEY is given.
    python scripts/smoke_test.py --offline
        Runs in-process against the real app with every external service
        mocked and the corpus-backed DB fixture (no keys, no database needed).

Exit code 0 = all executed checks passed. Skipped checks are reported, never
counted as passed.
"""

import argparse
import io
import os
import sys
import time
import uuid
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

RESULTS = []


def record(name, ok, detail="", skipped=False):
    RESULTS.append((name, ok, detail, skipped))
    tag = "SKIP" if skipped else ("PASS" if ok else "FAIL")
    print(f"[{tag}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def tiny_wav() -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * 16000)
    return buf.getvalue()


def run_checks(client, offline: bool, review_key: str = None):
    thread = f"smoke-{uuid.uuid4().hex[:8]}"

    r = client.get("/health/live")
    record("health/live", r.status_code == 200)
    r = client.get("/health/ready")
    ready = r.json() if r.status_code == 200 else {}
    record("health/ready", r.status_code == 200, str({k: v for k, v in ready.items() if k != "status"}))

    r = client.get("/languages")
    langs = [l["code"] for l in r.json().get("languages", [])] if r.status_code == 200 else []
    record("languages", "kn" in langs and "hi" in langs, f"{len(langs)} languages")

    t0 = time.time()
    r = client.post("/chat", json={"message": "I am a farmer from Karnataka with 2 acres growing ragi",
                                   "thread_id": thread, "language": "en"})
    body = r.json() if r.status_code == 200 else {}
    record("chat responds", r.status_code == 200 and body.get("status") != "error",
           f"status={body.get('status')} in {time.time() - t0:.1f}s")
    prof = body.get("current_profile") or {}
    record("profile extracted (needs LLM or demo mode)",
           prof.get("state") == "Karnataka" and prof.get("primary_crop") == "ragi",
           f"profile={ {k: v for k, v in prof.items() if v is not None} }")
    schemes = body.get("schemes") or []
    record("eligibility statuses present",
           bool(schemes) and all(s.get("eligibility_status") for s in schemes),
           f"{len(schemes)} schemes")
    record("XAI explanation present", any(s.get("xai_explanation") for s in schemes))
    record("documents / steps present", any(s.get("documents") for s in schemes)
           and any(s.get("application_steps") for s in schemes))
    record("session id echoed", body.get("thread_id") == thread)

    r = client.post("/chat", json={"message": "What documents do I need for the first one?",
                                   "thread_id": thread, "language": "en"})
    b2 = r.json() if r.status_code == 200 else {}
    first = schemes[0]["scheme_id"] if schemes else None
    got = [s.get("scheme_id") for s in b2.get("schemes") or []]
    record("follow-up resolves 'the first one'", bool(first) and got[:1] == [first], f"{got[:2]}")

    r = client.post("/chat", json={"message": "ನಾನು ರಾಗಿ ಬೆಳೆಯುತ್ತೇನೆ", "thread_id": thread, "language": "kn"})
    record("language switch keeps session", r.status_code == 200 and
           (r.json().get("current_profile") or {}).get("state") == "Karnataka")

    r = client.get("/schemes", params={"state": "Karnataka"})
    record("scheme search API", r.status_code == 200)

    # security smoke (§194)
    r = client.post("/chat", json={"message": "a" * 50000, "thread_id": thread})
    record("oversized message rejected", r.status_code == 422)
    r = client.post("/voice", files={"file": ("x.wav", b"not audio", "audio/wav")},
                    data={"thread_id": thread, "language": "en"})
    record("malformed audio rejected", (r.json().get("error") or {}).get("code") == "VALIDATION_ERROR")
    r = client.get("/schemes", params={"state": "' OR '1'='1"})
    record("SQL text handled safely", r.status_code < 500)

    sarvam = offline or ready.get("sarvam_configured")
    if sarvam:
        r = client.post("/tts", json={"text": "Namaste", "language_code": "kn"})
        record("TTS", r.status_code == 200 and bool(r.json().get("audio_base64")))
        r = client.post("/voice", files={"file": ("rec.wav", tiny_wav(), "audio/wav")},
                        data={"thread_id": thread, "language": "kn"})
        record("voice endpoint reachable", r.status_code == 200, f"status={r.json().get('status')}")
    else:
        record("TTS", False, "Sarvam not configured", skipped=True)
        record("voice endpoint", False, "Sarvam not configured", skipped=True)

    if review_key:
        r = client.get("/review-cases", headers={"X-Review-Key": review_key})
        cases = r.json().get("cases", []) if r.status_code == 200 else []
        record("review queue reachable", r.status_code == 200, f"{len(cases)} cases")
        mine = [c for c in cases if c.get("session_id") == thread and c["status"] == "PENDING"]
        if mine:
            cid = mine[0]["case_id"]
            client.post(f"/review-cases/{cid}/resolve", json={"action": "REQUEST_INFORMATION"},
                        headers={"X-Review-Key": review_key})
            r = client.post(f"/review-cases/{cid}/resolve", json={"action": "APPROVE", "note": "smoke"},
                            headers={"X-Review-Key": review_key})
            record("review case resolved", r.status_code == 200 and r.json()["case"]["status"] == "RESOLVED")
        else:
            record("review case resolved", False, "no pending case for this session", skipped=True)
    else:
        record("review API", False, "no --review-key given", skipped=True)
    r = client.get("/review-cases")
    record("review API rejects missing key", r.status_code == 403)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--review-key", default=os.environ.get("REVIEW_API_KEY"))
    args = ap.parse_args()
    if not args.base_url and not args.offline:
        ap.error("give --base-url or --offline")

    if args.offline:
        import logging
        import evaluation  # noqa: F401  (backend import path)
        logging.disable(logging.CRITICAL)
        from fastapi.testclient import TestClient
        from app.main import app
        from app.core.config import settings
        from evaluation.fixtures.corpus_db import CorpusDB
        from evaluation.fixtures.mock_services import (
            offline_environment, ScriptedProfileLLM, FakeWebSearch, FakeTranslator, FakeVoice,
        )
        settings.REVIEW_API_KEY = args.review_key = args.review_key or "smoke-offline-key"
        script = ScriptedProfileLLM({
            "I am a farmer from Karnataka with 2 acres growing ragi":
                {"state": "Karnataka", "land_size_acres": 2, "primary_crop": "ragi", "occupation": "farmer"},
            "I grow ragi": {"primary_crop": "ragi"},
        })
        tr = FakeTranslator({"ನಾನು ರಾಗಿ ಬೆಳೆಯುತ್ತೇನೆ": "I grow ragi"})
        with offline_environment(db=CorpusDB(), profile_llm=script, translator=tr,
                                 web=FakeWebSearch([]), voice=FakeVoice({tiny_wav(): "I grow ragi"})):
            run_checks(TestClient(app), offline=True, review_key=args.review_key)
    else:
        import httpx
        with httpx.Client(base_url=args.base_url, timeout=120) as client:
            run_checks(client, offline=False, review_key=args.review_key)

    executed = [r for r in RESULTS if not r[3]]
    failed = [r for r in executed if not r[1]]
    print(f"\n{len(executed) - len(failed)}/{len(executed)} executed checks passed, "
          f"{len(RESULTS) - len(executed)} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
