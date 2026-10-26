"""
Retrieval evaluation (Phase 7 §21–§28, §120).

DB, Knowledge Graph and Tavily channels are evaluated separately and then
merged. DB = corpus fixture, Graph = real NetworkX snapshot, Tavily = fixture.
"""

import asyncio
import time
from typing import Any, Dict, List, Set

from evaluation.metrics import mean, precision_at_k, recall_at_k, safe_ratio, summarize_checks
from evaluation.runners.common import load_dataset, check
from evaluation.fixtures.mock_services import offline_environment, FakeWebSearch


def _applicable(ds, sid: str, profile: Dict[str, Any]) -> bool:
    """Ground-truth applicability from the dataset's hand-written targeting maps."""
    states = ds["state_targeted_schemes"].get(sid)
    crops = ds["crop_targeted_schemes"].get(sid)
    if states and profile.get("state") and profile["state"] not in states:
        return False
    if crops and profile.get("primary_crop") and profile["primary_crop"].lower() not in crops:
        return False
    return True


def _state(profile, query="", referenced=None, intent="scheme_search"):
    return {"profile": profile, "contextual_query": query, "query_intent": intent,
            "referenced_scheme_id": referenced}


async def _channel_results(profile):
    from app.retrieval.request_builder import build_retrieval_request
    from app.retrieval.db_retriever import search_db
    from app.retrieval.graph_retriever import search_graph
    req = build_retrieval_request(profile=profile, contextual_query="")
    db, graph = [], []
    try:
        db = await search_db(req)
    except Exception:
        pass
    try:
        graph = await search_graph(req)
    except Exception:
        pass
    return db, graph


def run(corpus_db) -> Dict[str, Any]:
    from app.agents.retrieval_agent import retrieval_agent_node
    from app.retrieval.merger import merge_results
    from app.retrieval.models import RetrievalResult, SourceType

    ds = load_dataset("retrieval_cases.json")
    k = ds["k"]
    corpus_ids = set(corpus_db.scheme_ids())
    web = FakeWebSearch(ds["web_fixture"])

    merged_rows, db_rows, graph_rows = [], [], []
    with offline_environment(db=corpus_db, web=web):
        for case in ds["profile_cases"]:
            profile = case["profile"]
            out = asyncio.run(retrieval_agent_node(_state(profile)))
            merged = [c["scheme_id"] for c in out["merged_candidates"]]
            db_res, graph_res = asyncio.run(_channel_results(profile))
            db_ids = [r.scheme_id for r in db_res]
            graph_ids = [r.scheme_id for r in graph_res]
            for rows, ids in ((merged_rows, merged), (db_rows, db_ids), (graph_rows, graph_ids)):
                applicable = [s for s in ids if _applicable(ds, s, profile)]
                rows.append({
                    "id": case["case_id"],
                    "returned": len(ids),
                    "precision_at_k": precision_at_k(ids, applicable, k),
                    "targeted_recall_at_k": recall_at_k(ids, case["targeted"], k),
                    "targeted_missing_at_k": sorted(set(case["targeted"]) - set(ids[:k])),
                    "excluded_found": sorted(set(case["excluded"]) & set(ids)),
                    "state_filter_ok": not any(s in ids for s in case["excluded"]
                                               if s in ds["state_targeted_schemes"]),
                    "crop_filter_ok": not any(s in ids for s in case["excluded"]
                                              if s in ds["crop_targeted_schemes"]),
                    "only_real_schemes": all(s in corpus_ids for s in ids),
                })

    # Lookups run with an empty web fixture so DB/graph behaviour is isolated.
    lookup_checks = []
    with offline_environment(db=corpus_db, web=FakeWebSearch([])):
        for case in ds["lookup_cases"]:
            if case.get("referenced_scheme_id"):
                out = asyncio.run(retrieval_agent_node(_state({}, referenced=case["referenced_scheme_id"],
                                                              intent="scheme_details")))
                ids = [c["scheme_id"] for c in out["merged_candidates"]]
                lookup_checks.append(check(case["case_id"], bool(ids) and ids[0] == case["expected_top1"],
                                           returned=ids[:3]))
                continue
            query = case["query"] * case.get("repeat", 1)
            try:
                out = asyncio.run(retrieval_agent_node(_state({}, query=query)))
                ids = [c["scheme_id"] for c in out["merged_candidates"]]
                crashed = False
            except Exception as e:  # recorded as a failure, never raised
                ids, crashed = [], repr(e)
            ok = not crashed
            if case.get("expected_empty"):
                ok = ok and not ids
            if case.get("expected_include"):
                ok = ok and set(case["expected_include"]) <= set(ids)
            if case.get("expect_only_real_schemes"):
                ok = ok and all(i in corpus_ids for i in ids)
            lookup_checks.append(check(case["case_id"], ok, returned=ids[:5], crashed=crashed,
                                       query_len=len(query)))

    # ── merge (§27) ───────────────────────────────────────────────
    from app.retrieval.web_retriever import _try_resolve_scheme_id
    merge_checks = []
    for case in ds["merge_cases"]:
        db = [RetrievalResult(source_type=SourceType.DATABASE, scheme_id=s, title=s, source_name="db")
              for s in case["db"]]
        graph = [RetrievalResult(source_type=SourceType.KNOWLEDGE_GRAPH, scheme_id=s, title=s,
                                 source_name="graph", evidence={"matched_nodes": ["state"],
                                                                "matched_relations": ["state"]})
                 for s in case["graph"]]
        webr = [RetrievalResult(source_type=SourceType.LIVE_WEB, scheme_id=_try_resolve_scheme_id(t) or None,
                                title=t, source_name=t, source_url="https://example.gov.in/x")
                for t in case["web_titles"]]
        merged, _ = merge_results(db, graph, webr)
        ids = sorted(c.scheme_id for c in merged)
        srcs = {c.scheme_id: sorted(s.value for s in c.retrieval_sources) for c in merged}
        exp_srcs = {k2: sorted(v) for k2, v in case["expected_sources"].items()}
        merge_checks.append(check(case["case_id"], ids == sorted(case["expected_ids"]) and srcs == exp_srcs,
                                  ids=ids, sources=srcs))

    # ── source conflict (§28) ─────────────────────────────────────
    conflict_checks = []
    for case in ds["conflict_cases"]:
        db = [RetrievalResult(source_type=SourceType.DATABASE, scheme_id=case["scheme_id"], title="x",
                              benefits=case["db_benefits"], source_name="db")]
        webr = [RetrievalResult(source_type=SourceType.LIVE_WEB, scheme_id=case["scheme_id"], title="x",
                                benefits=case["web_benefits"], source_name="web")]
        merged, conflicts = merge_results(db, [], webr)
        kept = merged[0].benefit_summary == case["db_benefits"]
        conflict_checks.append(check(case["case_id"],
                                     bool(conflicts) == case["expect_conflict"] and kept,
                                     conflicts=len(conflicts), db_value_kept=kept))

    # ── failure matrix (§26) ──────────────────────────────────────
    failure_checks = []
    for case in ds["failure_matrix"]:
        corpus_db.fail = not case["db"]
        fw = FakeWebSearch(ds["web_fixture"], fail=not case["web"])
        with offline_environment(db=corpus_db, web=fw, graph_available=case["graph"]):
            out = asyncio.run(retrieval_agent_node(_state({"state": "Karnataka", "primary_crop": "ragi"})))
        corpus_db.fail = False
        errors = out.get("retrieval_errors", {})
        expected_err = {n for n, ok in (("database", case["db"]), ("knowledge_graph", case["graph"]),
                                        ("live_web", case["web"])) if not ok}
        srcs: Set[str] = set()
        for c in out["merged_candidates"]:
            srcs |= set(c.get("retrieval_sources", []))
        healthy_srcs = {n for n, ok in (("DATABASE", case["db"]), ("KNOWLEDGE_GRAPH", case["graph"]),
                                        ("LIVE_WEB", case["web"])) if ok}
        ok = set(errors) == expected_err and srcs <= healthy_srcs
        if not healthy_srcs:
            ok = ok and not out["merged_candidates"]
        failure_checks.append(check(case["case_id"], ok, expected_errors=sorted(expected_err),
                                    reported_errors=sorted(errors), candidate_sources=sorted(srcs),
                                    candidates=len(out["merged_candidates"])))

    # ── Tavily pipeline (§24) ─────────────────────────────────────
    with offline_environment(db=corpus_db, web=FakeWebSearch(ds["web_fixture"])):
        out = asyncio.run(retrieval_agent_node(_state({"state": "Karnataka", "primary_crop": "ragi"})))
    web_sources = [s for c in out["merged_candidates"] for s in c.get("sources", [])
                   if s.get("type") == "LIVE_WEB"]
    web_urls = {s.get("url") for s in web_sources}
    tavily = {
        "url_preserved": "https://pmkisan.gov.in/" in web_urls,
        "known_scheme_linked": any("LIVE_WEB" in c.get("retrieval_sources", []) and c["scheme_id"] == "PM_KISAN"
                                   for c in out["merged_candidates"]),
        "unrelated_result_not_a_candidate": not any("random-blog" in (s.get("url") or "") for s in web_sources),
        "web_sources_seen": sorted(u for u in web_urls if u),
    }
    tavily_checks = [check(k2, v) for k2, v in tavily.items() if isinstance(v, bool)]

    parallel = parallel_benchmark(corpus_db)

    def agg(rows):
        return {
            "cases": len(rows),
            "mean_precision_at_k": mean([r["precision_at_k"] for r in rows]),
            "mean_targeted_recall_at_k": mean([r["targeted_recall_at_k"] for r in rows]),
            "exclusion_violations": sum(len(r["excluded_found"]) for r in rows),
            "state_filter_accuracy": safe_ratio(sum(r["state_filter_ok"] for r in rows), len(rows)),
            "crop_filter_accuracy": safe_ratio(sum(r["crop_filter_ok"] for r in rows), len(rows)),
            "only_real_schemes": all(r["only_real_schemes"] for r in rows),
            "cases_missing_targeted": [{"id": r["id"], "missing": r["targeted_missing_at_k"]}
                                       for r in rows if r["targeted_missing_at_k"]],
        }

    return {
        "k": k,
        "merged": agg(merged_rows),
        "database": agg(db_rows),
        "knowledge_graph": agg(graph_rows),
        "lookups": summarize_checks(lookup_checks),
        "merge": summarize_checks(merge_checks),
        "source_conflicts": summarize_checks(conflict_checks),
        "failure_matrix": summarize_checks(failure_checks),
        "tavily_pipeline": {**summarize_checks(tavily_checks), "details": tavily},
        "parallel": parallel,
    }


def parallel_benchmark(corpus_db) -> Dict[str, Any]:
    """§25 / §120: DB=2s, Graph=1s, Web=3s mocked delays → ≈3s if concurrent, ≈6s if sequential."""
    import app.agents.retrieval_agent as ra

    orig = {"db": ra.search_db, "graph": ra.search_graph, "web": ra.search_web}

    def delayed(fn, seconds):
        async def wrapper(req):
            await asyncio.sleep(seconds)
            return await fn(req)
        return wrapper

    ra.search_db = delayed(orig["db"], 2.0)
    ra.search_graph = delayed(orig["graph"], 1.0)
    ra.search_web = delayed(orig["web"], 3.0)
    try:
        with offline_environment(db=corpus_db, web=FakeWebSearch([])):
            t0 = time.perf_counter()
            asyncio.run(ra.retrieval_agent_node(_state({"state": "Karnataka", "primary_crop": "ragi"})))
            elapsed = time.perf_counter() - t0
    finally:
        ra.search_db, ra.search_graph, ra.search_web = orig["db"], orig["graph"], orig["web"]
    return {
        "mock_delays_s": {"database": 2.0, "knowledge_graph": 1.0, "live_web": 3.0},
        "sequential_expected_s": 6.0,
        "parallel_expected_s": 3.0,
        "measured_s": round(elapsed, 3),
        "concurrent": elapsed < 4.0,
    }
