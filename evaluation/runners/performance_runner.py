"""
Performance, load and stability evaluation (Phase 7 §115–§128).

OFFLINE numbers measure the system's own processing time with every external
service mocked (zero network latency). They are NOT the Review-II 10–15 s
user-facing target, which depends on Groq/Tavily/Sarvam latency and can only
be measured with --live.
"""

import asyncio
import gc
import time
from typing import Any, Dict, List

from evaluation.metrics import latency_summary, safe_ratio
from evaluation.runners.common import load_dataset, new_thread, make_wav
from evaluation.fixtures.mock_services import (
    offline_environment, ScriptedProfileLLM, FakeWebSearch, FakeTranslator, FakeVoice,
)

PROFILES = [
    ("I am a farmer from Karnataka with 2 acres growing ragi",
     {"state": "Karnataka", "land_size_acres": 2, "primary_crop": "ragi", "occupation": "farmer"}),
    ("I am a farmer in Maharashtra with 8 acres of cotton",
     {"state": "Maharashtra", "land_size_acres": 8, "primary_crop": "cotton", "occupation": "farmer"}),
    ("I grow groundnut on 4 acres in Andhra Pradesh",
     {"state": "Andhra Pradesh", "land_size_acres": 4, "primary_crop": "groundnut"}),
    ("I am a woman farmer in Assam with 1 acre of rice",
     {"state": "Assam", "land_size_acres": 1, "primary_crop": "rice", "gender": "female", "occupation": "farmer"}),
    ("I am a 30 year old farmer in Uttar Pradesh with 2 acres of wheat",
     {"state": "Uttar Pradesh", "land_size_acres": 2, "primary_crop": "wheat", "occupation": "farmer", "age": 30}),
]



def rss_kb() -> float:
    """Resident set size of this process in KB (no tracing overhead)."""
    try:
        import ctypes
        import ctypes.wintypes as wt

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = wt.HANDLE
        fn = ctypes.windll.psapi.GetProcessMemoryInfo
        fn.argtypes = [wt.HANDLE, ctypes.POINTER(PMC), wt.DWORD]
        fn(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb)
        return round(pmc.WorkingSetSize / 1024, 1)
    except Exception:
        import resource
        return float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def _script():
    return ScriptedProfileLLM({u: e for u, e in PROFILES})


async def _stage_timings(utterance: str) -> Dict[str, float]:
    """Per-node wall time from LangGraph's streaming updates (§115 breakdown)."""
    from langchain_core.messages import HumanMessage
    from app.graph.workflow import kisan_agent
    cfg = {"configurable": {"thread_id": new_thread("perf-stage")}}
    timings: Dict[str, float] = {}
    t_prev = time.perf_counter()
    async for chunk in kisan_agent.astream({"messages": [HumanMessage(content=utterance)]}, config=cfg):
        now = time.perf_counter()
        for node in (chunk or {}):
            timings[node] = timings.get(node, 0.0) + (now - t_prev) * 1000
        t_prev = now
    return timings


async def _load(app, n: int, concurrency: int, body_fn) -> Dict[str, Any]:
    import httpx
    sem = asyncio.Semaphore(concurrency)
    latencies: List[float] = []
    errors = {"http_error": 0, "app_error": 0, "exception": 0}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://eval",
                                 timeout=60) as client:
        async def one(i):
            async with sem:
                t0 = time.perf_counter()
                try:
                    r = await client.post("/chat", json=body_fn(i))
                    latencies.append((time.perf_counter() - t0) * 1000)
                    if r.status_code != 200:
                        errors["http_error"] += 1
                    elif r.json().get("status") == "error":
                        errors["app_error"] += 1
                except Exception:
                    errors["exception"] += 1
        await asyncio.gather(*(one(i) for i in range(n)))
    failed = sum(errors.values())
    return {"requests": n, "concurrency": concurrency, "errors": errors,
            "error_rate": safe_ratio(failed, n), "latency": latency_summary(latencies)}


def run(corpus_db, soak_seconds: int = 0) -> Dict[str, Any]:
    from fastapi.testclient import TestClient
    from app.main import app
    import app.services.knowledge_graph_service as kg

    client = TestClient(app)
    out: Dict[str, Any] = {"mode": "offline (all external services mocked, zero network latency)"}

    # count graph (re)loads during the whole run (§125)
    load_calls = {"n": 0}
    orig_load = kg.load_graph_snapshot

    def counting_load(*a, **k):
        load_calls["n"] += 1
        return orig_load(*a, **k)

    with offline_environment(db=corpus_db, profile_llm=_script(), web=FakeWebSearch([])):
        kg.load_graph_snapshot = counting_load
        try:
            # ── text latency, 25 representative complete-profile requests (§116, §195) ──
            text_lat = []
            for i in range(25):
                utter = PROFILES[i % len(PROFILES)][0]
                t0 = time.perf_counter()
                r = client.post("/chat", json={"message": utter, "thread_id": new_thread("perf")})
                text_lat.append((time.perf_counter() - t0) * 1000)
                assert r.status_code == 200
            out["text_request"] = latency_summary(text_lat)

            # ── per-stage breakdown (§115) ────────────────────────
            stages: Dict[str, List[float]] = {}
            for utter, _ in PROFILES:
                for node, ms in asyncio.run(_stage_timings(utter)).items():
                    stages.setdefault(node, []).append(ms)
            out["stage_breakdown_ms"] = {k: latency_summary(v) for k, v in stages.items()}

            # ── per-language text latency (§118), mocked translation ──
            ml = load_dataset("multilingual_cases.json")
            meaning = ml["parity_groups"]["G1"]["meaning"]
            lang_lat: Dict[str, List[float]] = {}
            for case in [c for c in ml["cases"] if c["group"] == "G1"]:
                script = ScriptedProfileLLM({meaning: ml["parity_groups"]["G1"]["extraction"]})
                tr = FakeTranslator({case["input"]: meaning})
                with offline_environment(db=corpus_db, profile_llm=script, translator=tr, web=FakeWebSearch([])):
                    for _ in range(3):
                        t0 = time.perf_counter()
                        client.post("/chat", json={"message": case["input"], "thread_id": new_thread("lang"),
                                                   "language": case["language"]})
                        lang_lat.setdefault(case["language"], []).append((time.perf_counter() - t0) * 1000)
            out["language_latency"] = {k: latency_summary(v) for k, v in lang_lat.items()}

            # ── voice latency (§117), mocked ASR/TTS ──────────────
            audio = make_wav("perf-voice")
            fv = FakeVoice({audio: PROFILES[0][0]})
            voice_lat = []
            with offline_environment(db=corpus_db, profile_llm=_script(), voice=fv, web=FakeWebSearch([])):
                for _ in range(20):
                    t0 = time.perf_counter()
                    r = client.post("/voice", files={"file": ("r.wav", audio, "audio/wav")},
                                    data={"thread_id": new_thread("pv"), "language": "en"})
                    client.post("/tts", json={"text": (r.json().get("reply") or "")[:500], "language_code": "en"})
                    voice_lat.append((time.perf_counter() - t0) * 1000)
            out["voice_round_trip"] = latency_summary(voice_lat)

            # ── load test (§121) ──────────────────────────────────
            body = lambda i: {"message": PROFILES[i % len(PROFILES)][0], "thread_id": new_thread(f"load{i}")}
            out["load_sequential"] = asyncio.run(_load(app, 100, 1, body))
            out["load_concurrent"] = asyncio.run(_load(app, 200, 10, body))

            # ── memory plateau (§121, §122) ───────────────────────
            # Conversations are kept in memory up to MAX_SESSIONS by design, so the
            # meaningful check is that memory stops growing once the cap is reached.
            # Cap lowered to 100 for the measurement; 300 more requests are sent.
            from app.graph import workflow
            saved_cap = workflow.memory.max_threads
            workflow.memory.max_threads = 100
            try:
                checkpoints = []
                for i in range(300):
                    client.post("/chat", json={"message": PROFILES[i % 5][0], "thread_id": new_thread("mem")})
                    if (i + 1) % 100 == 0:
                        gc.collect()
                        checkpoints.append(rss_kb())
            finally:
                workflow.memory.max_threads = saved_cap
            from app.services.review_service import get_queue_stats
            out["memory"] = {
                "session_cap_during_test": 100,
                "rss_kb_after_100_200_300": checkpoints,
                "rss_growth_kb_last_100_requests": round(checkpoints[-1] - checkpoints[-2], 1),
                "sessions_in_memory": len(workflow.memory.storage),
                "review_cases_in_memory": get_queue_stats()["total"],
                "note": "The in-memory review queue is not capped (academic simulation, §67).",
            }

            # ── short soak (§122) ─────────────────────────────────
            if soak_seconds > 0:
                t_end = time.time() + soak_seconds
                soak_lat, soak_err, i = [], 0, 0
                m_start = rss_kb()
                while time.time() < t_end:
                    t0 = time.perf_counter()
                    r = client.post("/chat", json={"message": PROFILES[i % 5][0], "thread_id": new_thread("soak")})
                    soak_lat.append((time.perf_counter() - t0) * 1000)
                    soak_err += int(r.status_code != 200 or r.json().get("status") == "error")
                    i += 1
                m_end = rss_kb()
                out["soak"] = {"duration_s": soak_seconds, "requests": i, "errors": soak_err,
                               "latency": latency_summary(soak_lat),
                               "rss_growth_kb": round(m_end - m_start, 1),
                               "target": "1-2 hours", "status": "PARTIAL (shorter than target)"}
            else:
                out["soak"] = {"status": "NOT_MEASURED", "reason": "soak disabled (use --soak-seconds)"}
        finally:
            kg.load_graph_snapshot = orig_load

    out["graph_reloads_during_run"] = load_calls["n"]
    out["db_connection_pool"] = {"status": "NOT_MEASURED",
                                 "reason": "Offline runs use the corpus fixture; pool behaviour needs PostgreSQL."}
    return out


def run_live() -> Dict[str, Any]:
    """Live /chat latency against real Groq/Tavily (requires API keys and a database)."""
    from app.core.config import settings
    missing = [k for k in ("GROQ_API_KEY", "TAVILY_API_KEY") if not getattr(settings, k)]
    if missing:
        return {"status": "NOT_MEASURED", "reason": f"missing {missing}"}
    from fastapi.testclient import TestClient
    from app.main import app
    lat, errors = [], 0
    with TestClient(app) as client:
        for i in range(20):
            thread = new_thread("live")
            t0 = time.perf_counter()
            r = client.post("/chat", json={"message": PROFILES[i % 5][0], "thread_id": thread})
            lat.append((time.perf_counter() - t0) * 1000)
            errors += int(r.status_code != 200 or r.json().get("status") == "error")
    s = latency_summary(lat)
    p95 = s["p95_ms"] or 0
    return {"status": "MEASURED", "requests": 20, "errors": errors, "latency": s,
            "review2_target_s": "10-15", "achieved": "ACHIEVED" if p95 <= 15000 else
            ("PARTIAL" if (s["p50_ms"] or 0) <= 15000 else "NOT_ACHIEVED")}
