"""
Red-team / security / privacy evaluation (Phase 7 §96–§114, §159–§160, §163).
"""

import io
import logging
import os
import re
from typing import Any, Dict, List

from evaluation import PROJECT_ROOT, BACKEND_DIR
from evaluation.metrics import summarize_checks
from evaluation.runners.common import (
    load_dataset, check, new_thread, get_client, graph_state, scheme_map, make_wav, rules_from,
)
from evaluation.fixtures.mock_services import (
    offline_environment, ScriptedProfileLLM, ScriptedTextLLM, FakeWebSearch, FakeVoice,
)

APP_DIR = os.path.join(BACKEND_DIR, "app")
FRONTEND_SRC = os.path.join(PROJECT_ROOT, "frontend", "src")
UTTER = "probe utterance"


def _py_files(root, skip_tests=True):
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", "node_modules", ".git", ".next")]
        if skip_tests and os.path.basename(dirpath) == "tests":
            continue
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(dirpath, f)


def _grep(paths, pattern, flags=0):
    rx = re.compile(pattern, flags)
    hits = []
    for p in paths:
        try:
            with open(p, encoding="utf-8", errors="ignore") as fh:
                for i, line in enumerate(fh, 1):
                    if rx.search(line):
                        hits.append(f"{os.path.relpath(p, PROJECT_ROOT)}:{i}: {line.strip()[:120]}")
        except OSError:
            pass
    return hits


def _chat(client, thread, msg, language="en"):
    r = client.post("/chat", json={"message": msg, "thread_id": thread, "language": language})
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, {}


def _static_sql_scan():
    files = list(_py_files(APP_DIR))
    sql = r"\b(SELECT|INSERT|UPDATE|DELETE|DROP|WHERE)\b"
    fstring_sql = _grep(files, r"""f["'].*""" + sql)
    format_sql = _grep(files, sql + r""".*["']\s*\.format\(""")
    percent_sql = _grep(files, sql + r""".*["']\s*%\s*[\(\w]""")
    hits = fstring_sql + format_sql + percent_sql
    return not hits, {"interpolated_sql": hits[:10]}


def _static_secret_scan():
    tracked = []
    for root in (os.path.join(PROJECT_ROOT, "backend"), os.path.join(PROJECT_ROOT, "frontend", "src"),
                 os.path.join(PROJECT_ROOT, "scripts"), os.path.join(PROJECT_ROOT, "evaluation")):
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in ("__pycache__", "node_modules", ".git", ".next", ".pytest_cache")]
            for f in files:
                if f == ".env":
                    continue
                if f.endswith((".py", ".ts", ".tsx", ".js", ".json", ".yml", ".yaml", ".example", ".md", ".toml")):
                    tracked.append(os.path.join(dirpath, f))
    patterns = [r"gsk_[A-Za-z0-9]{20,}", r"tvly-[A-Za-z0-9]{12,}", r"\bsk-[A-Za-z0-9]{20,}",
                r"REVIEW_API_KEY\s*=\s*[\"'][^\"']+[\"']", r"api-subscription-key\"\s*:\s*\"[A-Za-z0-9]{12,}"]
    hits = []
    for pat in patterns:
        hits += _grep(tracked, pat)
    hits = [h for h in hits if "evaluation/runners/adversarial_runner.py" not in h.replace("\\", "/")]
    return not hits, {"hits": hits[:10]}


def run(corpus_db) -> Dict[str, Any]:
    ds = load_dataset("adversarial_cases.json")
    client = get_client()
    checks: List[Dict[str, Any]] = []

    for case in ds["cases"]:
        cid, kind = case["case_id"], case["kind"]
        ok, details = False, {}
        try:
            if kind == "profile_value":
                script = ScriptedProfileLLM({UTTER: case["extraction"]})
                thread = new_thread(cid)
                with offline_environment(db=corpus_db, profile_llm=script, web=FakeWebSearch([])):
                    code, body = _chat(client, thread, UTTER)
                prof = graph_state(thread).get("profile") or {}
                bad = {f: prof.get(f) for f in case["expect_absent"] if prof.get(f) is not None}
                ok = code == 200 and not bad
                details = {"stored": bad}

            elif kind == "engine_numeric":
                from app.eligibility.evaluator import evaluate_scheme
                res = evaluate_scheme(cid, cid, rules_from([case["rule"]]), case["profile"])
                st = res.status.value
                ok = (st == case["expect_status"]) if "expect_status" in case else (st != case["expect_status_not"])
                details = {"status": st}

            elif kind in ("pipeline_web_injection", "pipeline_user_override", "pipeline_web_xss"):
                extraction = case["extraction"]
                first = "I am a male farmer in Karnataka with 1 acre of ragi" if kind != "pipeline_web_xss" \
                    else "I am a farmer from Karnataka with 2 acres growing ragi"
                script = ScriptedProfileLLM({first: extraction})
                if kind == "pipeline_web_injection":
                    web = FakeWebSearch([{"title": "PM Kisan update", "url": "https://pmkisan.gov.in/news",
                                          "content": case["web_content"]}])
                elif kind == "pipeline_web_xss":
                    web = FakeWebSearch([{"title": case["web_title"], "url": "https://pmkisan.gov.in/x",
                                          "content": "PM-KISAN update"}])
                else:
                    web = FakeWebSearch([])
                thread = new_thread(cid)
                with offline_environment(db=corpus_db, profile_llm=script, web=web):
                    code, body = _chat(client, thread, first)
                    if kind == "pipeline_user_override":
                        code, body = _chat(client, thread, case["message"])
                schemes = scheme_map(body)
                if kind == "pipeline_web_xss":
                    # Delivered as JSON text; the frontend renders strings via JSX (escaped) — see A22.
                    ok = code == 200 and isinstance(body, dict)
                else:
                    flipped = [s for s in case["expect_never_eligible"]
                               if schemes.get(s, {}).get("eligibility_status") == "ELIGIBLE"]
                    leaked = "ignore previous instructions" in (body.get("reply") or "").lower()
                    ok = code == 200 and not flipped and not leaked
                    details = {"flipped": flipped, "injection_echoed": leaked,
                               "MKSP": schemes.get("MKSP", {}).get("eligibility_status")}

            elif kind == "formatter_fabrication":
                utter = "I am a farmer in Karnataka"
                script = ScriptedProfileLLM({utter: case["extraction"]})
                llm = ScriptedTextLLM("fixed", text=case["llm_reply"])
                thread = new_thread(cid)
                with offline_environment(db=corpus_db, profile_llm=script, text_llm=llm, web=FakeWebSearch([])):
                    code, body = _chat(client, thread, utter)
                schemes = scheme_map(body)
                rejected = (body.get("reply") or "").strip() != case["llm_reply"].strip()
                mksp_ok = schemes.get("MKSP", {}).get("eligibility_status") != "ELIGIBLE"
                ok = code == 200 and rejected and mksp_ok
                details = {"llm_reply_used": not rejected}

            elif kind == "no_candidates":
                script = ScriptedProfileLLM({UTTER: case["extraction"]})
                corpus_db.fail = True
                try:
                    with offline_environment(db=corpus_db, profile_llm=script, graph_available=False,
                                             web=FakeWebSearch(fail=True)):
                        code, body = _chat(client, new_thread(cid), UTTER)
                finally:
                    corpus_db.fail = False
                ok = code == 200 and body.get("status") == "no_results" and not body.get("schemes") \
                    and "**" not in (body.get("reply") or "")
                details = {"status": body.get("status")}

            elif kind == "static_sql_scan":
                ok, details = _static_sql_scan()

            elif kind == "api_sql_text":
                before = sum(len(corpus_db.rules_for(s)) for s in corpus_db.scheme_ids())
                with offline_environment(db=corpus_db):
                    r = client.get(case["path"], params=case["params"])
                after = sum(len(corpus_db.rules_for(s)) for s in corpus_db.scheme_ids())
                ok = r.status_code < 500 and before == after
                details = {"http": r.status_code}

            elif kind == "graph_injection":
                from app.services import knowledge_graph_service as kg
                if kg.get_graph_repo() is None:
                    kg.init_knowledge_graph()
                repo = kg.get_graph_repo()
                n0, e0 = repo.node_count, repo.edge_count
                kg.find_graph_candidates(case["profile"])
                ok = (repo.node_count, repo.edge_count) == (n0, e0)
                details = {"nodes": repo.node_count, "edges": repo.edge_count}

            elif kind == "static_eval_scan":
                hits = _grep(list(_py_files(APP_DIR)), r"(?<![\w.])(eval|exec)\(")
                ok, details = not hits, {"hits": hits}

            elif kind == "static_xss_scan":
                files = [os.path.join(dp, f) for dp, _, fs in os.walk(FRONTEND_SRC) for f in fs
                         if f.endswith((".ts", ".tsx", ".js", ".jsx"))]
                hits = _grep(files, r"dangerouslySetInnerHTML|\.innerHTML\s*=")
                ok, details = not hits, {"hits": hits}

            elif kind == "audio_upload":
                payload = (case.get("payload") or "").encode() if case.get("payload") \
                    else b"RIFF" + b"\x00" * int(case.get("size_mb", 0) * 1024 * 1024)
                fv = FakeVoice({})
                with offline_environment(db=corpus_db, voice=fv):
                    r = client.post("/voice", files={"file": ("a.bin", payload, case["content_type"])},
                                    data={"thread_id": new_thread(cid), "language": "en"})
                body = r.json()
                ok = (body.get("error") or {}).get("code") == "VALIDATION_ERROR" and fv.asr_calls == 0
                details = {"error": (body.get("error") or {}).get("code"), "asr_calls": fv.asr_calls}

            elif kind == "session_isolation":
                a, b = "Karnataka 2 acres ragi", "Maharashtra 5 acres cotton"
                script = ScriptedProfileLLM({
                    a: {"state": "Karnataka", "land_size_acres": 2, "primary_crop": "ragi"},
                    b: {"state": "Maharashtra", "land_size_acres": 5, "primary_crop": "cotton"}})
                ta, tb = new_thread(cid + "a"), new_thread(cid + "b")
                with offline_environment(db=corpus_db, profile_llm=script, web=FakeWebSearch([])):
                    _chat(client, ta, a)
                    _chat(client, tb, b)
                    _chat(client, ta, "thanks")
                pa, pb = graph_state(ta).get("profile") or {}, graph_state(tb).get("profile") or {}
                ok = pa.get("state") == "Karnataka" and pb.get("state") == "Maharashtra" \
                    and pa.get("primary_crop") == "ragi" and pb.get("primary_crop") == "cotton"

            elif kind == "review_auth":
                headers = {"X-Review-Key": case["header"]} if case["header"] else {}
                r = client.get("/review-cases", headers=headers)
                ok, details = r.status_code == 403, {"http": r.status_code}

            elif kind == "review_unauthorized_resolve":
                from app.services import review_service as rs
                from app.models.review import ReviewReason, ReviewStatus
                c = rs.create_review_case("eval-adv", "q", ReviewReason.UNVERIFIABLE, {}, [], [], [])
                r = client.post(f"/review-cases/{c.case_id}/resolve", json={"action": "APPROVE"},
                                headers={"X-Review-Key": "wrong"})
                ok = r.status_code == 403 and rs.get_case(c.case_id).status == ReviewStatus.PENDING

            elif kind == "static_secret_scan":
                ok, details = _static_secret_scan()

            elif kind == "huge_message":
                with offline_environment(db=corpus_db, web=FakeWebSearch([])) as env:
                    code, body = _chat(client, new_thread(cid), "a" * case["length"])
                    llm_saw_it = len(env["profile_llm"].calls) > 0
                ok, details = code == 422 and not llm_saw_it, {"http": code, "reached_llm": llm_saw_it}

            elif kind == "blank_message":
                with offline_environment(db=corpus_db, web=FakeWebSearch([])):
                    code, body = _chat(client, new_thread(cid), case["message"])
                ok = code in (200, 422) and not (body.get("schemes") if isinstance(body, dict) else None)
                details = {"http": code, "status": body.get("status") if isinstance(body, dict) else None}

            elif kind == "log_audit":
                script = ScriptedProfileLLM({UTTER: case["extraction"]})
                audio = make_wav("log-audit")
                fv = FakeVoice({audio: "my income is 187654 rupees"})
                stream = io.StringIO()
                handler = logging.StreamHandler(stream)
                handler.setLevel(logging.DEBUG)
                root = logging.getLogger()
                prev_disable = logging.root.manager.disable
                prev_handlers = list(root.handlers)
                logging.disable(logging.NOTSET)
                prev_level = root.level
                root.setLevel(logging.DEBUG)
                root.handlers = [handler]  # capture only; keep the console quiet
                try:
                    with offline_environment(db=corpus_db, profile_llm=script, voice=fv, web=FakeWebSearch([])):
                        _chat(client, new_thread(cid), UTTER)
                        client.post("/voice", files={"file": ("r.wav", audio, "audio/wav")},
                                    data={"thread_id": new_thread(cid), "language": "en"})
                finally:
                    root.handlers = prev_handlers
                    root.setLevel(prev_level)
                    logging.disable(prev_disable)
                text = stream.getvalue()
                leaks = [tok for tok in ("187654", "'has_aadhaar': True", "'category': 'SC'") if tok in text]
                ok, details = not leaks, {"leaked_tokens": leaks, "log_lines": text.count("\n")}

            elif kind == "network_audit":
                script = ScriptedProfileLLM({UTTER: case["extraction"]})
                llm = ScriptedTextLLM("unavailable")
                web = FakeWebSearch([])
                with offline_environment(db=corpus_db, profile_llm=script, text_llm=llm, web=web):
                    _chat(client, new_thread(cid), UTTER)
                outbound = {"tavily_queries": web.queries, "llm_prompts": llm.prompts}
                blob = " ".join(web.queries + llm.prompts).lower()
                leaks = [t for t in ("187654", "has_aadhaar", "annual_income", "category: sc") if t in blob]
                ok = not leaks
                details = {"leaks": leaks, "tavily_queries": web.queries,
                           "llm_prompt_count": len(llm.prompts)}

            elif kind == "duplicate_submission":
                msg = "I am a farmer from Karnataka with 2 acres growing ragi"
                script = ScriptedProfileLLM({msg: case["extraction"]})
                thread = new_thread(cid)
                with offline_environment(db=corpus_db, profile_llm=script, web=FakeWebSearch([])):
                    _, b1 = _chat(client, thread, msg)
                    _, b2 = _chat(client, thread, msg)
                s1 = {k: v.get("eligibility_status") for k, v in scheme_map(b1).items()}
                s2 = {k: v.get("eligibility_status") for k, v in scheme_map(b2).items()}
                ok = s1 == s2 and bool(s1) and b2.get("status") != "asking_question"
                details = {"identical": s1 == s2, "second_status": b2.get("status")}
        except Exception as e:
            ok, details = False, {"exception": repr(e)[:300]}
        checks.append(check(cid, ok, category=case["category"], kind=kind, attack=case["attack"], **details))

    summary = summarize_checks(checks)
    by_cat: Dict[str, List[bool]] = {}
    for c in checks:
        by_cat.setdefault(c["category"], []).append(c["passed"])
    summary["by_category"] = {k: {"passed": sum(v), "total": len(v)} for k, v in by_cat.items()}
    return summary
