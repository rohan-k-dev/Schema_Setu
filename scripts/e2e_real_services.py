"""
End-to-end farmer flows against the running stack with the REAL services (Groq, Tavily, Sarvam,
official websites) — nothing mocked. Needs the API keys in backend/.env and `docker compose up`.

    python scripts/e2e_real_services.py [--api http://localhost:8000]

1. English question → profile extracted by the LLM, eligible schemes + alternatives, live check of
   official sources with timestamps, grounded reply.
2. Follow-up about one scheme ("tell me more about the first one") in the same conversation.
3. Hindi question → reply in Hindi (Sarvam translation), same deterministic eligibility.
4. Voice round trip: Sarvam text-to-speech makes a real Kannada recording of a farmer's question, the
   /voice endpoint transcribes it (Sarvam speech-to-text) and answers with schemes.
Prints measured latencies. Each request uses a fresh conversation.
"""

import argparse
import base64
import re
import sys
import time
import uuid

import httpx

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" - {detail}" if detail and not ok else ""))


def thread():
    return f"e2e-{uuid.uuid4().hex[:10]}"


def chat(c, message, thread_id, language="en"):
    t = time.perf_counter()
    r = c.post("/chat", json={"message": message, "thread_id": thread_id, "language": language})
    return r, round(time.perf_counter() - t, 1)


def main(api):
    c = httpx.Client(base_url=api, timeout=180, headers={"Origin": "http://localhost:3000"})
    ready = c.get("/health/ready").json()
    check("all services configured", all(ready.get(k) for k in ("groq_configured", "tavily_configured",
                                                               "sarvam_configured", "db_ready")), str(ready))

    # 1. English
    th = thread()
    r, dt = chat(c, "I am a small farmer from Karnataka. I grow ragi on 2 acres and I am 45 years old. "
                    "Which government schemes can help me with crop insurance or income support?", th)
    d = r.json()
    print(f"  english: {dt}s status={d.get('status')} summary={d.get('recommendation_summary')}")
    p = d.get("current_profile") or {}
    check("LLM extracted the profile", p.get("state") == "Karnataka" and p.get("land_size_acres") == 2.0
          and (p.get("primary_crop") or "").lower() == "ragi" and p.get("age") == 45, str(p))
    schemes = d.get("schemes") or []
    secs = {s.get("recommendation_section") for s in schemes}
    check("eligible schemes and alternatives returned", "ELIGIBLE" in secs and "ALTERNATIVE" in secs, str(secs))
    elig = [s for s in schemes if s.get("recommendation_section") == "ELIGIBLE"]
    check("section A only engine-eligible", all(s["eligibility_status"] == "ELIGIBLE" for s in elig))
    lc = d.get("live_check") or {}
    check("live check ran on official sources", lc.get("performed") and lc.get("discovery", {}).get("status")
          in ("OK", "PARTIAL"), str({k: lc.get(k) for k in ("sources_accessed", "sources_failed")}))
    fresh = [s for s in schemes if (s.get("freshness") or {}).get("sources")]
    check("results carry source links and timestamps", all(src.get("url") and (src.get("checked_at"))
                                                           for s in fresh for src in s["freshness"]["sources"]))
    reply = re.sub("[   ]", " ", d.get("reply") or "")       # LLM may use no-break spaces
    check("reply mentions an eligible scheme by name", any(s["name"].split(" (")[0][:20].lower() in reply.lower()
                                                           for s in elig) or "PM-KISAN" in reply, reply[:300])
    check("reply doesn't claim alternatives are eligible", "not confirmed" in reply.lower(), reply[-400:])
    check("english latency under 15 s", dt <= 15, f"{dt}s")

    # 2. Follow-up in the same conversation
    r2, dt2 = chat(c, "Tell me more about the first one. What documents do I need?", th)
    d2 = r2.json()
    print(f"  follow-up: {dt2}s status={d2.get('status')}")
    check("follow-up answered in context", r2.status_code == 200 and d2.get("status") in
          ("scheme_details", "schemes_found") and len(d2.get("reply") or "") > 40, (d2.get("reply") or "")[:200])

    # 3. Hindi
    r3, dt3 = chat(c, "मैं महाराष्ट्र का किसान हूँ, 3 एकड़ में कपास उगाता हूँ। मेरे लिए कौन सी सरकारी योजनाएँ हैं?",
                   thread(), "hi")
    d3 = r3.json()
    reply3 = d3.get("reply") or ""
    print(f"  hindi: {dt3}s status={d3.get('status')} profile={d3.get('current_profile')}")
    check("hindi: profile extracted", (d3.get("current_profile") or {}).get("state") == "Maharashtra",
          str(d3.get("current_profile")))
    check("hindi: reply in Devanagari", len(re.findall(r"[ऀ-ॿ]", reply3)) > 40, reply3[:200])
    check("hindi: schemes with eligibility", bool(d3.get("schemes")))

    # 4. Voice round trip (Kannada)
    question_kn = "ನಾನು ಕರ್ನಾಟಕದ ರೈತ. ನಾನು ಎರಡು ಎಕರೆಯಲ್ಲಿ ರಾಗಿ ಬೆಳೆಯುತ್ತೇನೆ. ನನಗೆ ಯಾವ ಯೋಜನೆಗಳು ಸಿಗುತ್ತವೆ?"
    t = c.post("/tts", json={"text": question_kn, "language_code": "kn"})
    audio_b64 = (t.json() if t.status_code == 200 else {}).get("audio_base64")
    check("Sarvam text-to-speech produced audio", bool(audio_b64), t.text[:200])
    if audio_b64:
        wav = base64.b64decode(audio_b64)
        t0 = time.perf_counter()
        v = c.post("/voice", files={"file": ("question.wav", wav, "audio/wav")},
                   data={"thread_id": thread(), "language": "kn"})
        dv = round(time.perf_counter() - t0, 1)
        dv_json = v.json() if v.headers.get("content-type", "").startswith("application/json") else {}
        print(f"  voice: {dv}s status={dv_json.get('status')} transcript={dv_json.get('user_transcript')!r}")
        check("speech-to-text transcribed the question", bool(dv_json.get("user_transcript")), v.text[:300])
        check("voice answer has schemes", bool(dv_json.get("schemes")), str(dv_json.get("status")))
        check("voice profile: Karnataka", (dv_json.get("current_profile") or {}).get("state") == "Karnataka",
              str(dv_json.get("current_profile")))

    print(f"\n{sum(results)}/{len(results)} passed")
    return all(results)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    sys.exit(0 if main(ap.parse_args().api) else 1)
