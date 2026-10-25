"""
Phase 7 regression tests — one or more tests per bug in docs/phase7-bug-register.md.

Every test here failed on the pre-fix code (see data/evaluation/reports/before/)
and must keep passing.
"""

import asyncio
import logging
import math
import os
import re
from dataclasses import dataclass
from typing import Any, Optional

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJECT_DIR = os.path.dirname(BACKEND_DIR)


@dataclass
class Rule:
    field_name: str
    operator: str
    value_json: Any = None
    logical_group: str = "AND"
    required: bool = True
    source_text: Optional[str] = None
    unit: Optional[str] = None
    rule_id: Optional[str] = None


def _evaluate(rules, profile, **kw):
    from app.eligibility.evaluator import evaluate_scheme
    return evaluate_scheme("S", "Scheme", rules, profile, **kw)


# ─── BUG-001: application must import (API tests used to be skipped silently) ──

def test_bug001_app_imports_and_serves_health():
    from fastapi.testclient import TestClient
    from app.main import app
    r = TestClient(app).get("/health/live")
    assert r.status_code == 200


# ─── BUG-002: OR-group detection by substring ──────────────────

def test_bug002_group_name_containing_or_letters_is_and():
    rules = [Rule("land_size_acres", "LTE", 5, "land_for_smallholders"),
             Rule("land_size_acres", "GTE", 1, "land_for_smallholders")]
    assert _evaluate(rules, {"land_size_acres": 9}).status.value == "NOT_ELIGIBLE"


@pytest.mark.parametrize("name,expected", [("OR", True), ("or", True), ("category_or", True),
                                           ("OR_region", True), ("AND", False), ("MAJOR", False),
                                           ("land_for_smallholders", False), ("", False)])
def test_bug002_is_or_group(name, expected):
    from app.eligibility.logical import is_or_group
    assert is_or_group(name) is expected


# ─── BUG-003 / BUG-030: numeric parsing ────────────────────────

@pytest.mark.parametrize("raw,expected", [("-3", None), (-3, None), ("nan", None), ("inf", None),
                                          (float("nan"), None), ("1.5 lakhs", 150000.0),
                                          ("2 lac", 200000.0), ("1 crore", 1e7), ("₹1,50,000", 150000.0),
                                          (True, None)])
def test_bug003_safe_parse_numeric(raw, expected):
    from app.eligibility.normalizer import safe_parse_numeric
    assert safe_parse_numeric(raw) == expected


def test_bug003_negative_string_never_passes_upper_bound():
    res = _evaluate([Rule("land_size_acres", "LTE", 5)], {"land_size_acres": "-3"})
    assert res.status.value != "ELIGIBLE"


# ─── BUG-004: occupation / age kept; has_land derived ──────────

def test_bug004_profile_keeps_occupation_and_age():
    from app.models.profile import FarmerProfile
    p = FarmerProfile(occupation="Farmer", age=35)
    assert p.occupation == "farmer" and p.age == 35


@pytest.mark.parametrize("profile,status", [
    ({"occupation": "farmer", "land_size_acres": 2}, "ELIGIBLE"),
    ({"occupation": "farmer", "land_size_acres": 0}, "NOT_ELIGIBLE"),
    ({"occupation": "farmer"}, "NEEDS_MORE_INFORMATION"),
    ({"occupation": "farmer", "land_size_acres": 2, "has_land": False}, "NOT_ELIGIBLE"),
])
def test_bug004_has_land_derivation(profile, status):
    rules = [Rule("occupation", "EQ", "farmer"), Rule("has_land", "BOOLEAN", True)]
    assert _evaluate(rules, profile).status.value == status


# ─── BUG-005: review escalation on real engine results ─────────

def test_bug005_real_unverifiable_result_escalates():
    from app.services.review_service import should_escalate
    from app.models.review import ReviewReason
    assert should_escalate([_evaluate([], {"state": "Karnataka"})], [], {}) == ReviewReason.UNVERIFIABLE


def test_bug005_rule_conflict_reason_wins_over_unverifiable():
    from app.services.review_service import should_escalate
    from app.models.review import ReviewReason
    res = _evaluate([Rule("land_size_acres", "LTE", 5), Rule("land_size_acres", "GTE", 10)],
                    {"land_size_acres": 3})
    assert res.status.value == "UNVERIFIABLE"
    assert should_escalate([res], [], {}) == ReviewReason.RULE_CONFLICT


def test_bug005_escalate_if_needed_dedupes_per_session():
    from app.services.review_service import escalate_if_needed
    res = _evaluate([], {})
    a = escalate_if_needed("sess-dedupe", "q", {"aadhaar_number": "1234"}, [res], [], {})
    b = escalate_if_needed("sess-dedupe", "q", {}, [res], [], {})
    assert a is not None and a.case_id == b.case_id
    assert "aadhaar_number" not in a.profile_snapshot
    assert a.eligibility_results[0]["status"] == "UNVERIFIABLE"


# ─── BUG-006 / BUG-007: retrieval relevance and graph restrictions ──

@pytest.fixture(scope="module")
def graph_repo():
    from app.services import knowledge_graph_service as kg
    if kg.get_graph_repo() is None:
        assert kg.init_knowledge_graph()
    return kg.get_graph_repo()


def test_bug007_graph_excludes_schemes_restricted_to_other_crops_and_states(graph_repo):
    ids = {c.scheme_id for c in graph_repo.find_candidates_for_profile(
        {"state": "Karnataka", "primary_crop": "ragi"})}
    assert not ids & {"NMOOP", "MIDH", "NFSM", "MOVCDNER", "STATE_MH_NAMO", "STATE_UP_KISAN"}
    assert "STATE_KA_KRUSHAK" in ids


def test_bug006_graph_ranks_targeted_schemes_first(graph_repo):
    cands = graph_repo.find_candidates_for_profile({"state": "Andhra Pradesh", "primary_crop": "groundnut"})
    top = [c.scheme_id for c in cands[:3]]
    assert "STATE_AP_RYTHU" in top and "NMOOP" in top


def test_bug006_merger_puts_targeted_candidates_first():
    from app.retrieval.merger import merge_results
    from app.retrieval.models import RetrievalResult, SourceType
    db = [RetrievalResult(source_type=SourceType.DATABASE, scheme_id=s, title=s, source_name="db",
                          evidence={"targeting": t})
          for s, t in (("AAA_GENERAL", []), ("ZZZ_STATE", ["state_targeted"]))]
    merged, _ = merge_results(db, [], [])
    assert [c.scheme_id for c in merged] == ["ZZZ_STATE", "AAA_GENERAL"]


# ─── BUG-008 / BUG-028: failures reported; empty is not a failure ──

def test_bug008_graph_retriever_raises_when_unavailable():
    from app.services import knowledge_graph_service as kg
    from app.retrieval.graph_retriever import search_graph
    from app.retrieval.models import RetrievalRequest
    saved = kg._graph_available
    kg._graph_available = False
    try:
        with pytest.raises(RuntimeError):
            asyncio.run(search_graph(RetrievalRequest(state="Karnataka")))
    finally:
        kg._graph_available = saved


def test_bug008_retrieval_agent_records_channel_errors(monkeypatch):
    import app.agents.retrieval_agent as ra

    async def boom(_):
        raise ConnectionError("down")

    async def empty(_):
        return []

    monkeypatch.setattr(ra, "search_db", boom)
    monkeypatch.setattr(ra, "search_graph", empty)
    monkeypatch.setattr(ra, "search_web", boom)
    out = asyncio.run(ra.retrieval_agent_node({"profile": {"state": "Karnataka"}, "contextual_query": "",
                                               "query_intent": "scheme_search"}))
    assert set(out["retrieval_errors"]) == {"database", "live_web"}
    assert out["retrieval_metadata"]["retrieval_success"]["knowledge_graph"] is True


# ─── BUG-009 / BUG-010: Tavily URLs kept; web identity map ─────

def test_bug009_search_service_keeps_url_and_title(monkeypatch):
    import app.services.search_service as ss

    class Client:
        def search(self, **_):
            return {"results": [{"title": "PM-KISAN", "url": "https://pmkisan.gov.in/", "content": "x"}]}

    monkeypatch.setattr(ss, "_get_tavily_client", lambda: Client())
    out = asyncio.run(ss.search_web_schemes("q"))
    assert out[0]["url"] == "https://pmkisan.gov.in/" and out[0]["title"] == "PM-KISAN"


def test_bug009_search_service_raises_on_failure(monkeypatch):
    import app.services.search_service as ss
    from app.core.exceptions import ExternalServiceError

    class Client:
        def search(self, **_):
            raise ConnectionError("down")

    monkeypatch.setattr(ss, "_get_tavily_client", lambda: Client())
    with pytest.raises(ExternalServiceError):
        asyncio.run(ss.search_web_schemes("q"))


def test_bug010_kusum_resolves_to_corpus_id():
    from app.retrieval.web_retriever import _try_resolve_scheme_id
    assert _try_resolve_scheme_id("PM KUSUM solar pump scheme") == "PM_KUSUM"


# ─── BUG-011: empty query with empty profile ───────────────────

def test_bug011_empty_request_returns_nothing():
    from app.retrieval.db_retriever import search_db
    from app.retrieval.models import RetrievalRequest
    assert asyncio.run(search_db(RetrievalRequest(query="  "))) == []


# ─── BUG-012: scheme cards carry documents / steps / source / XAI ──

def test_bug012_response_schemes_include_candidate_details():
    from app.agents.response_formatter import _build_response_schemes
    from app.recommendation.ranker import rank_results
    res = _evaluate([Rule("occupation", "EQ", "farmer")], {"occupation": "farmer"})
    res.scheme_id = "PM_KISAN"
    cand = {"scheme_id": "PM_KISAN", "documents": ["Aadhaar Card"], "application_steps": ["Apply online"],
            "official_url": "https://pmkisan.gov.in", "graph_evidence": ["state"], "sources": []}
    card = _build_response_schemes([cand], rank_results([res]))[0]
    assert card["documents"] == ["Aadhaar Card"] and card["application_steps"] == ["Apply online"]
    assert card["official_url"] == "https://pmkisan.gov.in" and card["graph_evidence"] == ["state"]
    assert card["eligibility_status"] == "ELIGIBLE" and card["xai_explanation"]


# ─── BUG-013: LLM reply grounding ──────────────────────────────

SCHEMES = [
    {"scheme_id": "PM_KISAN", "name": "Pradhan Mantri Kisan Samman Nidhi (PM-KISAN)",
     "eligibility_status": "ELIGIBLE", "benefit_summary": "Rs. 6,000 per year",
     "official_url": "https://pmkisan.gov.in"},
    {"scheme_id": "MKSP", "name": "Mahila Kisan Sashaktikaran Pariyojana",
     "eligibility_status": "NOT_ELIGIBLE", "official_url": None},
]


@pytest.mark.parametrize("reply", [
    "Good news! You are eligible for the Mahila Kisan Sashaktikaran Pariyojana.",
    "You are eligible for all schemes listed.",
    "Apply at https://free-money.example.com/register now.",
    "PM-KISAN gives Rs. 10,000 every year.",
    "1. **Kisan Golden Harvest Yojana** - extra support.",
])
def test_bug013_fabricated_llm_replies_rejected(reply):
    from app.xai.response_validator import validate_llm_response
    ok, reasons = validate_llm_response(reply, SCHEMES)
    assert not ok and reasons


def test_bug013_grounded_llm_reply_accepted():
    from app.xai.response_validator import validate_llm_response
    reply = ("Based on the available published criteria, your profile matches **PM-KISAN**, which gives "
             "Rs. 6,000 per year (https://pmkisan.gov.in). You are not eligible for MKSP.")
    ok, reasons = validate_llm_response(reply, SCHEMES)
    assert ok, reasons


def test_bug013_formatter_falls_back_when_llm_fabricates(monkeypatch):
    import app.services.llm_service as llm
    from langchain_core.runnables import RunnableLambda
    from app.agents.response_formatter import response_formatter_node
    from app.recommendation.ranker import rank_results

    monkeypatch.setattr(llm, "_get_llm", lambda: RunnableLambda(lambda _: "You are eligible for all schemes!"))
    res = _evaluate([Rule("gender", "EQ", "female")], {"gender": "male"})
    res.scheme_id = "MKSP"
    out = asyncio.run(response_formatter_node({
        "merged_candidates": [{"scheme_id": "MKSP", "name": "MKSP"}],
        "recommendation_results": rank_results([res]), "retrieval_errors": {}, "profile": {}}))
    assert "eligible for all" not in out["response_text"].lower()
    assert out["response_schemes"][0]["eligibility_status"] == "NOT_ELIGIBLE"


# ─── BUG-014: explanation validator ────────────────────────────

def test_bug014_validator_rejects_fabrication_and_accepts_genuine():
    from app.xai.explainer import explain_for_response, validate_explanation
    res = _evaluate([Rule("land_size_acres", "LTE", 5, source_text="Up to 5 acres")], {"land_size_acres": 10})
    text = explain_for_response(res)
    assert validate_explanation(text, res)
    assert not validate_explanation(text + "\nYou are eligible for this scheme.", res)
    assert not validate_explanation(text + "\nMaximum land allowed is 37 acres.", res)
    assert not validate_explanation(text + "\nSource: https://fake.example.org", res)
    assert not validate_explanation(text + "\n✓ Crop: matches", res)


def test_bug014_or_group_eligible_explanation_is_consistent():
    from app.xai.explainer import explain_for_response, validate_explanation
    rules = [Rule("category", "IN", ["sc", "st"], "OR"), Rule("gender", "EQ", "female", "OR")]
    res = _evaluate(rules, {"category": "General", "gender": "female"})
    text = explain_for_response(res)
    assert res.status.value == "ELIGIBLE"
    assert "Does not match" not in text and validate_explanation(text, res)


# ─── BUG-015: rule provenance URL ──────────────────────────────

def test_bug015_source_url_attached_to_rules():
    res = _evaluate([Rule("state", "EQ", "karnataka", source_text="KA")], {"state": "Karnataka"},
                    source_url="https://raitamitra.karnataka.gov.in")
    assert res.rule_results[0].source_url == "https://raitamitra.karnataka.gov.in"
    assert res.source_references[0]["url"] == "https://raitamitra.karnataka.gov.in"


# ─── BUG-016: question fallback is field-specific ──────────────

def test_bug016_question_uses_template_when_llm_fails(monkeypatch):
    import app.services.llm_service as llm
    from langchain_core.runnables import RunnableLambda
    from app.agents.question_agent import question_agent_node, FIELD_QUESTIONS

    def down(_):
        raise ConnectionError("llm down")

    monkeypatch.setattr(llm, "_get_llm", lambda: RunnableLambda(down))
    out = asyncio.run(question_agent_node({"missing_fields": ["state", "land_size_acres"], "messages": []}))
    assert out["response_text"] == FIELD_QUESTIONS["state"]


# ─── BUG-017: deterministic profile canonicalisation ───────────

@pytest.mark.parametrize("field,raw,expected", [
    ("state", "karnataka", "Karnataka"), ("state", "KA", "Karnataka"), ("state", "Xyzland", None),
    ("state", "Karnataka'; DROP TABLE schemes;--", None), ("primary_crop", "Paddy", "rice"),
    ("primary_crop", "moongfali", "groundnut"), ("category", "scheduled caste", "SC"),
    ("gender", "woman", "female"), ("land_size_acres", -5, None), ("land_size_acres", "NaN", None),
    ("annual_income", "inf", None), ("land_size_acres", 0, 0.0), ("age", 150, None),
])
def test_bug017_profile_canonicalisation(field, raw, expected):
    from app.models.profile import FarmerProfile
    assert getattr(FarmerProfile(**{field: raw}), field) == expected


def test_bug017_invalid_value_does_not_discard_valid_fields():
    from app.models.profile import FarmerProfile
    p = FarmerProfile(state="Karnataka", annual_income="abc", primary_crop="ragi")
    assert p.state == "Karnataka" and p.primary_crop == "ragi" and p.annual_income is None


# ─── BUG-018: ordinal follow-up resolution ─────────────────────

@pytest.mark.parametrize("query,prev,expected", [
    ("What documents do I need for the second one?", ["A", "B", "C"], ("resolved", "B", 2)),
    ("tell me about scheme 3", ["A", "B", "C"], ("resolved", "C", 3)),
    ("the last one please", ["A", "B"], ("resolved", "B", 2)),
    ("What about the second one?", ["A"], ("out_of_range", None, 2)),
    ("I grow ragi", ["A"], None),
])
def test_bug018_resolve_ordinal_reference(query, prev, expected):
    from app.agents.query_rewriter import resolve_ordinal_reference
    assert resolve_ordinal_reference(query, prev) == expected


def test_bug018_rewriter_asks_for_clarification_when_out_of_range():
    from app.agents.query_rewriter import query_rewriter_node
    out = asyncio.run(query_rewriter_node({"original_query": "What about the second one?", "profile": {},
                                           "messages": [], "response_schemes": [{"scheme_id": "PM_KISAN"}]}))
    assert out["needs_clarification"] is True and out["referenced_scheme_id"] is None


# ─── BUG-019: deterministic ranking ────────────────────────────

def test_bug019_ties_broken_by_scheme_id_and_graph_evidence_used():
    import itertools
    from app.eligibility.models import EligibilityResult, EligibilityStatus
    from app.recommendation.ranker import rank_results
    rs = [EligibilityResult(scheme_id=s, status=EligibilityStatus.ELIGIBLE, passed_rules=1)
          for s in ("PMFBY", "KCC", "PM_KISAN")]
    orders = {tuple(r.scheme_id for r in rank_results(list(p))) for p in itertools.permutations(rs)}
    assert len(orders) == 1
    ranked = rank_results(rs, graph_evidence=[{"scheme_id": "PMFBY", "evidence": ["state"]}])
    assert ranked[0].scheme_id == "PMFBY" and "Knowledge graph match" in ranked[0].rank_reasons


# ─── BUG-020: reviewer key from environment ────────────────────

def test_bug020_no_hardcoded_reviewer_key():
    with open(os.path.join(BACKEND_DIR, "app", "api", "review.py"), encoding="utf-8") as f:
        src = f.read()
    assert not re.search(r"REVIEW_API_KEY\s*=\s*[\"']", src)


def test_bug020_review_api_disabled_without_key_and_open_with_key(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.config import settings
    client = TestClient(app)
    monkeypatch.setattr(settings, "REVIEW_API_KEY", None)
    assert client.get("/review-cases", headers={"X-Review-Key": "anything"}).status_code == 403
    monkeypatch.setattr(settings, "REVIEW_API_KEY", "test-key-123")
    assert client.get("/review-cases", headers={"X-Review-Key": "wrong"}).status_code == 403
    assert client.get("/review-cases", headers={"X-Review-Key": "test-key-123"}).status_code == 200


# ─── BUG-021 / BUG-022: privacy in logs and outbound prompts ───

def test_bug021_profile_values_not_logged(monkeypatch, caplog):
    import app.services.llm_service as llm
    from langchain_core.runnables import RunnableLambda
    from app.models.profile import FarmerProfile
    from app.agents.profile_agent import profile_agent_node
    monkeypatch.setattr(llm, "_get_structured_llm", lambda: RunnableLambda(
        lambda _: FarmerProfile(annual_income=187654, category="SC", has_aadhaar=True)))
    with caplog.at_level(logging.DEBUG):
        asyncio.run(profile_agent_node({"messages": [("human", "x")], "profile": {"annual_income": 100}}))
    assert "187654" not in caplog.text and "'SC'" not in caplog.text


def test_bug022_llm_profile_summary_is_minimal():
    from app.utils.privacy import llm_safe_profile_summary
    s = llm_safe_profile_summary({"state": "Karnataka", "annual_income": 187654, "category": "SC",
                                  "has_aadhaar": True, "gender": "female", "primary_crop": "ragi"})
    assert "Karnataka" in s and "ragi" in s
    assert "187654" not in s and "SC" not in s and "aadhaar" not in s.lower() and "female" not in s


# ─── BUG-023: request limits ───────────────────────────────────

def test_bug023_huge_and_blank_messages_rejected():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    assert client.post("/chat", json={"message": "a" * 100000}).status_code == 422
    assert client.post("/chat", json={"message": "    "}).status_code == 422


# ─── BUG-024: audio content sniffing ───────────────────────────

@pytest.mark.parametrize("ctype,header,ok", [
    ("audio/wav", b"RIFF\x00\x00\x00\x00WAVEfmt ", True),
    ("audio/webm", bytes([0x1A, 0x45, 0xDF, 0xA3]) + b"\x00" * 8, True),
    ("audio/webm;codecs=opus", b"OggS" + b"\x00" * 8, True),
    ("audio/wav", b"this is not audio", False),
    ("audio/webm", b"<?php system($_GET['c']); ?>", False),
    ("audio/wav", b"OggS" + b"\x00" * 8, False),
])
def test_bug024_audio_sniffing(ctype, header, ok):
    from app.utils.validation import validate_audio_upload
    assert validate_audio_upload(ctype, 100, header=header)[0] is ok


# ─── BUG-025: bounded session store with O(1) equality ─────────

def test_bug025_bounded_memory_saver():
    from app.graph.workflow import BoundedMemorySaver
    saver = BoundedMemorySaver(max_threads=3)
    for i in range(5):
        saver.put({"configurable": {"thread_id": f"t{i}"}}, {"ts": f"2026-01-01T00:00:0{i}", "v": 1})
    assert list(saver.storage) == ["t2", "t3", "t4"]
    other = BoundedMemorySaver(max_threads=3)
    assert saver == saver and saver != other
    assert "t2" not in repr(saver)


# ─── BUG-026: no string-built SQL ──────────────────────────────

def test_bug026_no_fstring_sql_in_application_code():
    rx = re.compile(r"""f["'].*\b(SELECT|INSERT|UPDATE|DELETE|DROP)\b""")
    for root, _, files in os.walk(os.path.join(BACKEND_DIR, "app")):
        if "tests" in root:
            continue
        for name in files:
            if name.endswith(".py"):
                with open(os.path.join(root, name), encoding="utf-8") as f:
                    for line in f:
                        assert not rx.search(line), f"{name}: {line.strip()}"


# ─── BUG-027: profile constant not leaked as a field ───────────

def test_bug027_critical_fields_not_serialised():
    from app.models.profile import FarmerProfile
    assert "CRITICAL_FIELDS" not in FarmerProfile().model_dump()
    assert "CRITICAL_FIELDS" not in FarmerProfile.model_json_schema().get("properties", {})


# ─── BUG-029: categorical rule conflicts ───────────────────────

def test_bug029_disjoint_required_values_are_a_conflict():
    res = _evaluate([Rule("state", "IN", ["karnataka"]), Rule("state", "IN", ["maharashtra"])],
                    {"state": "Karnataka"})
    assert res.status.value == "UNVERIFIABLE"
    assert res.conflicts[0]["type"] == "CONTRADICTORY_VALUES"


def test_bug029_or_alternatives_are_not_a_conflict():
    res = _evaluate([Rule("state", "EQ", "karnataka", "OR"), Rule("state", "EQ", "maharashtra", "OR")],
                    {"state": "Karnataka"})
    assert res.status.value == "ELIGIBLE"


# ─── BUG-031 / BUG-032: frontend session + status handling ─────

def _page_src():
    with open(os.path.join(PROJECT_DIR, "frontend", "src", "app", "page.tsx"), encoding="utf-8") as f:
        return f.read()


def test_bug031_frontend_does_not_send_constant_thread_id():
    src = _page_src()
    assert "const THREAD_ID" not in src
    assert re.search(
        r"sendChat\(\s*userMsg,\s*threadIdRef\.current,\s*language,",
        src,
    )


def test_bug031_backend_echoes_thread_id(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    import app.api.chat as chat
    from types import SimpleNamespace

    class FakeAgent:
        async def aget_state(self, config):
            return SimpleNamespace(values={})

        async def ainvoke(self, inputs, config):
            return {"response_status": "asking_question", "response_text": "Which state?", "messages": []}

    monkeypatch.setattr(chat, "kisan_agent", FakeAgent())
    body = TestClient(app).post("/chat", json={"message": "hi", "thread_id": "abc-123"}).json()
    assert body["status"] == "asking_question"
    assert body["thread_id"] == "abc-123"


def test_bug032_frontend_shows_reply_for_every_status():
    src = _page_src()
    assert "data.reply || fallback" in src
    assert 'data.status === "schemes_found" && data.schemes' not in src


# ─── BUG-034: follow-up about one scheme stays on that scheme ──

def test_bug034_referenced_scheme_is_the_only_candidate(monkeypatch):
    import app.agents.retrieval_agent as ra
    from app.retrieval.models import RetrievalResult, SourceType

    async def db(_):
        return [RetrievalResult(source_type=SourceType.DATABASE, scheme_id="KCC", title="KCC", source_name="db")]

    async def graph(_):
        return [RetrievalResult(source_type=SourceType.KNOWLEDGE_GRAPH, scheme_id=s, title=s, source_name="g")
                for s in ("KCC", "PKVY", "PMFBY")]

    async def web(_):
        return []

    monkeypatch.setattr(ra, "search_db", db)
    monkeypatch.setattr(ra, "search_graph", graph)
    monkeypatch.setattr(ra, "search_web", web)
    out = asyncio.run(ra.retrieval_agent_node({"profile": {"state": "Karnataka"}, "contextual_query": "",
                                               "query_intent": "documents", "referenced_scheme_id": "KCC"}))
    assert [c["scheme_id"] for c in out["merged_candidates"]] == ["KCC"]


# ─── BUG-035: health endpoints report graph status and real version ──

def test_bug035_health_reports_graph_and_version():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.config import APP_VERSION
    client = TestClient(app)
    body = client.get("/health").json()
    assert body["version"] == APP_VERSION and "graph_available" in body
    assert "graph_ready" in client.get("/health/ready").json()
    assert client.get("/").json()["version"] == APP_VERSION


# ─── BUG-036 (Phase 8): more matched criteria rank first within a status ──

def test_bug036_more_matched_criteria_rank_higher():
    from app.eligibility.models import EligibilityResult, EligibilityStatus
    from app.recommendation.ranker import rank_results
    rs = [EligibilityResult(scheme_id="AAA_ONE_RULE", status=EligibilityStatus.ELIGIBLE, passed_rules=1),
          EligibilityResult(scheme_id="ZZZ_TWO_RULES", status=EligibilityStatus.ELIGIBLE, passed_rules=2)]
    assert [r.scheme_id for r in rank_results(rs)] == ["ZZZ_TWO_RULES", "AAA_ONE_RULE"]


# ─── Phase 8: deployment fixes ─────────────────────────────────

@pytest.mark.parametrize("raw,expected", [("online", "ONLINE"), ("bank", "OFFICE"), ("online/CSC/bank", "HYBRID"),
                                          ("offline/online", "HYBRID"), ("CSC", "CSC"), ("by post", "UNKNOWN"),
                                          (None, None)])
def test_phase8_corpus_step_mode_matches_schema_constraint(raw, expected):
    from app.services.corpus_import_service import normalize_step_mode
    assert normalize_step_mode(raw) == expected


def test_phase8_selector_event_loop_policy_on_windows():
    import sys as _sys
    import asyncio as _asyncio
    import app.database.connection  # noqa: F401  (sets the policy on import)
    if _sys.platform == "win32":
        assert isinstance(_asyncio.get_event_loop_policy(), _asyncio.WindowsSelectorEventLoopPolicy)


def test_phase8_llm_unavailable_is_reported_not_looped(monkeypatch):
    """Without a working LLM the user is told the language service is unavailable."""
    import app.services.llm_service as llm
    from fastapi.testclient import TestClient
    from app.main import app
    from app.core.exceptions import ConfigurationError

    def not_configured():
        raise ConfigurationError("GROQ_API_KEY is not configured. Set it in your .env file.")

    monkeypatch.setattr(llm, "_get_structured_llm", not_configured)
    body = TestClient(app).post("/chat", json={"message": "I am from Karnataka", "thread_id": "p8-llm"}).json()
    assert body["status"] == "error"
    assert body["error"]["code"] == "LANGUAGE_SERVICE_UNAVAILABLE"
    assert "GROQ_API_KEY" not in str(body)


def test_phase8_configuration_errors_hidden_from_clients():
    from app.core.exceptions import ConfigurationError, ExternalServiceError, public_message
    assert ".env" not in public_message(ConfigurationError("SARVAM_API_KEY is not configured. Set it in your .env file."))
    assert public_message(ExternalServiceError("Sarvam ASR", "timed out")) == "Sarvam ASR: timed out"
