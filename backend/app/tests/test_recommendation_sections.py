"""
Eligible schemes + relevant alternatives (docs/RECOMMENDATIONS.md).

- Strict eligibility is unchanged: every (profile, scheme) decision equals the baseline captured
  from the pipeline BEFORE this feature (fixtures/recommendations/baseline_statuses.json), and
  Section A is exactly the engine's ELIGIBLE set.
- Alternatives: returned when not confirmed eligible, ranked by need / similarity / targeting,
  honest about missing information vs a known mismatch vs incomplete scheme data, never labelled
  eligible, de-duplicated across sections, with stored source links and dates (never invented).

Runs on the canonical corpus file through the real nodes (evaluation CorpusDB, no PostgreSQL,
LLM or web) — these are offline tests of the logic, not of live sources.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from app.eligibility.models import EligibilityResult, EligibilityStatus, RuleResult, RuleStatus
from app.recommendation import alternatives as alt
from app.tests.recommendation_harness import BASELINE, PROFILES, QUERIES, offline, run_pipeline, statuses


@pytest.fixture(scope="module")
def runs():
    import asyncio
    out = {}

    async def go():
        with offline():
            for name, profile in PROFILES.items():
                out[name] = await run_pipeline(profile, QUERIES[name])
    asyncio.run(go())
    return out


def sections_of(state) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {alt.ELIGIBLE: [], alt.ALTERNATIVE: [], alt.NOT_MATCHING: []}
    for s in state["response_schemes"]:
        out[s["recommendation_section"]].append(s)
    return out


# ─── strict eligibility unchanged ────────────────────────────────────────────

class TestStrictEligibilityUnchanged:
    def test_every_decision_equals_the_pre_feature_baseline(self, runs):
        baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
        for name, before in baseline.items():
            now = statuses(runs[name])
            changed = {sid: (st, now.get(sid)) for sid, st in before.items() if now.get(sid) != st}
            assert not changed, f"{name}: eligibility changed {changed}"
            assert len(now) >= len(before)              # more applicable schemes evaluated, none dropped

    def test_section_a_is_exactly_the_engine_eligible_set(self, runs):
        for name, state in runs.items():
            engine = {r.scheme_id for r in state["eligibility_results"] if r.status == EligibilityStatus.ELIGIBLE}
            hidden = {d["scheme_id"] for d in state["recommendation_sections"]["summary"]["duplicates_hidden"]}
            a = sections_of(state)[alt.ELIGIBLE]
            assert {s["scheme_id"] for s in a} == engine - hidden, name
            assert all(s["eligibility_status"] == "ELIGIBLE" and s["recommendation_status"] == alt.CONFIRMED_ELIGIBLE
                       for s in a)
            assert all(any("issuing department" in c for c in s["conditions_to_verify"]) for s in a)

    def test_eligible_order_still_follows_the_ranker(self, runs):
        for state in runs.values():
            a = [s for s in state["response_schemes"] if s["recommendation_section"] == alt.ELIGIBLE]
            assert [s["rank"] for s in a] == sorted(s["rank"] for s in a)


# ─── alternatives ────────────────────────────────────────────────────────────

class TestAlternatives:
    def test_relevant_schemes_returned_although_not_confirmed_eligible(self, runs):
        b = {s["scheme_id"]: s for s in sections_of(runs["ts_dairy"])[alt.ALTERNATIVE]}
        assert b["NLM"]["relevance"]["tier"] == 1 and b["NLM"]["relevance"]["rank"] == 1
        assert "livestock and dairy" in b["NLM"]["relevance"]["reasons"][0]
        assert b["NLM"]["recommendation_status"] == alt.ELIGIBILITY_UNCONFIRMED
        for s in b.values():
            assert s["eligibility_status"] != "ELIGIBLE" and "not confirmed" in s["status_text"].lower() or \
                s["recommendation_status"] == alt.KNOWN_MISMATCH
            assert s["relevance"]["reasons"], s["scheme_id"]

    def test_alternatives_widen_coverage_beyond_the_eligible_list(self, runs):
        for name, state in runs.items():
            sec = sections_of(state)
            assert len(sec[alt.ALTERNATIVE]) >= 10, name
            assert not {s["scheme_id"] for s in sec[alt.ELIGIBLE]} & {s["scheme_id"] for s in sec[alt.ALTERNATIVE]}

    def test_ranked_by_tier_then_score(self, runs):
        for state in runs.values():
            b = sections_of(state)[alt.ALTERNATIVE]
            keys = [(s["relevance"]["tier"], -s["relevance"]["score"]) for s in b]
            assert keys == sorted(keys)
            assert [s["relevance"]["rank"] for s in b] == list(range(1, len(b) + 1))

    def test_missing_information_is_not_a_mismatch(self, runs):
        for state in runs.values():
            for s in state["response_schemes"]:
                if s["eligibility_status"] == "NEEDS_MORE_INFORMATION":
                    assert s["recommendation_status"] == alt.ADDITIONAL_INFORMATION_REQUIRED
                    assert s["missing_information"] and not s["mismatches"]
                    assert any(c.startswith("Tell us:") for c in s["conditions_to_verify"])
                if s["eligibility_status"] == "UNVERIFIABLE":
                    assert s["recommendation_status"] in (alt.ELIGIBILITY_UNCONFIRMED, alt.SCHEME_INFORMATION_INCOMPLETE)
                    assert s["recommendation_section"] != alt.ELIGIBLE

    def test_known_ineligible_never_labelled_eligible(self, runs):
        for state in runs.values():
            for s in state["response_schemes"]:
                if s["eligibility_status"] == "NOT_ELIGIBLE":
                    assert s["recommendation_status"] == alt.KNOWN_MISMATCH
                    assert s["recommendation_section"] in (alt.ALTERNATIVE, alt.NOT_MATCHING)
                    assert s["mismatches"] and "requires" in s["mismatches"][0]
                    if s["recommendation_section"] == alt.ALTERNATIVE:      # only as a meaningful alternative
                        r = s["relevance"]
                        assert r["matched_needs"] or r["similar_to"]

    def test_duplicates_removed_across_sections(self, runs):
        for name, state in runs.items():
            ids = [s["scheme_id"] for s in state["response_schemes"]]
            assert len(ids) == len(set(ids)), name
            assert "PMKISAN_MAN_DHAN" not in ids                   # flagged duplicate of PM_KMY
            if any(r.scheme_id == "PM_KMY" for r in state["eligibility_results"]):
                assert "PM_KMY" in ids                              # the canonical record is the one kept

    def test_state_and_crop_targeting(self, runs):
        ka = {s["scheme_id"]: s for s in runs["ka_ragi_small"]["response_schemes"]}
        sk = ka["STATE_KA_KRUSHAK"]
        if sk["recommendation_section"] == alt.ALTERNATIVE:
            assert "A scheme specifically for Karnataka" in sk["relevance"]["reasons"]
        assert not any(s.get("applicable_states") and "Karnataka" not in s["applicable_states"] for s in ka.values())

    def test_sources_dates_and_missing_fields(self, runs):
        from evaluation.fixtures.corpus_db import CorpusDB
        db = CorpusDB()
        for state in runs.values():
            for s in state["response_schemes"]:
                raw = db._raw_by_id(s["scheme_id"])
                assert s["official_url"] == raw.get("official_url")               # stored link, not generated
                assert s["application_url"] == raw.get("application_url")         # None stays None
                assert s["last_verified_at"] == raw.get("last_verified_at")

    def test_profile_without_state_and_reply_note(self, runs):
        rj = runs["rj_no_state_crop_only"]
        assert rj["response_schemes"] and rj["recommendation_sections"]["summary"]["alternatives"] >= 1
        assert "not confirmed" in rj["response_text"]
        assert "Seeds, fertiliser and soil" in rj["recommendation_sections"]["summary"]["stated_needs"]


# ─── unit level: tiers, statuses, synthetic cases ────────────────────────────

def res(sid, status, passed=0, failed=None, unknown=None):
    rules = [RuleResult(field=f, operator="EQ", status=RuleStatus.FAIL, user_value=u, required_value=v)
             for f, u, v in failed or []]
    rules += [RuleResult(field=f, operator="EQ", status=RuleStatus.UNKNOWN) for f in unknown or []]
    rules += [RuleResult(field=f"ok{i}", operator="EQ", status=RuleStatus.PASS) for i in range(passed)]
    return EligibilityResult(scheme_id=sid, scheme_name=sid, status=status, rule_results=rules, passed_rules=passed,
                             failed_rules=len(failed or []), unknown_rules=len(unknown or []),
                             missing_information=list(unknown or []))


def cand(sid, name, desc="", targeting=(), **meta):
    return {"scheme_id": sid, "name": name, "description": desc, "matched_fields": list(targeting),
            "scheme_meta": {"possible_duplicate": False, "needs_review": False, **meta}}


class TestRankingUnits:
    def build(self, question="", profile=None):
        E, N, U, X = (EligibilityStatus.ELIGIBLE, EligibilityStatus.NEEDS_MORE_INFORMATION,
                      EligibilityStatus.UNVERIFIABLE, EligibilityStatus.NOT_ELIGIBLE)
        results = [res("PMFBY", E, passed=2), res("TN_INS", N, passed=1, unknown=["land_size_acres"]),
                   res("DAIRY", X, failed=[("occupation", "farmer", "dairy entrepreneur")]),
                   res("WEATHER", U), res("HOUSING", U), res("PENSION_X", X, failed=[("age", 61, "18-40")]),
                   res("NEW_REC", U)]
        cands = [cand("PMFBY", "Pradhan Mantri Fasal Bima Yojana", "crop insurance"),
                 cand("TN_INS", "State Crop Insurance Top-up", "crop insurance for farmers", ("state_targeted",)),
                 cand("DAIRY", "Dairy Entrepreneurship Scheme", "dairy units"),
                 cand("WEATHER", "Weather Based Crop Insurance", "insurance against weather"),
                 cand("HOUSING", "Rural Housing", "pucca house"),
                 cand("PENSION_X", "Farmer Pension Scheme", "pension"),
                 cand("NEW_REC", "Newly Found Irrigation Scheme", "drip irrigation", needs_review=True)]
        return alt.build_sections(results, cands, profile or {"state": "Tamil Nadu"}, question,
                                  rank_order=["PMFBY"])

    def test_tiers_and_order(self):
        out = self.build("I need dairy support")
        by = out["by_scheme"]
        assert by["PMFBY"]["section"] == alt.ELIGIBLE
        assert by["TN_INS"]["relevance"]["tier"] == 1                       # related, info missing, state-targeted
        assert by["WEATHER"]["relevance"]["tier"] == 2                      # same purpose as an eligible scheme
        assert "Pradhan Mantri Fasal Bima Yojana" in by["WEATHER"]["relevance"]["similar_to"]
        assert by["DAIRY"]["section"] == alt.ALTERNATIVE                    # mismatch, but the stated need
        assert by["PENSION_X"]["section"] == alt.NOT_MATCHING               # mismatch with no relation
        assert by["HOUSING"]["relevance"]["tier"] == 3
        order = [s for s in out["order"] if by[s]["section"] == alt.ALTERNATIVE]
        assert order.index("TN_INS") < order.index("WEATHER") < order.index("HOUSING")

    def test_need_match_outranks_plain_similarity(self):
        by = self.build("crop insurance please")["by_scheme"]
        assert by["WEATHER"]["relevance"]["tier"] == 1                       # now matches the stated need
        assert by["WEATHER"]["relevance"]["matched_needs"] == ["Crop insurance"]

    def test_statuses_are_honest(self):
        by = self.build()["by_scheme"]
        assert by["TN_INS"]["recommendation_status"] == alt.ADDITIONAL_INFORMATION_REQUIRED
        assert by["TN_INS"]["missing_information"] == ["land_size_acres"]
        assert by["WEATHER"]["recommendation_status"] == alt.ELIGIBILITY_UNCONFIRMED
        assert by["NEW_REC"]["recommendation_status"] == alt.SCHEME_INFORMATION_INCOMPLETE  # unreviewed record
        assert by["DAIRY"]["recommendation_status"] == alt.KNOWN_MISMATCH
        assert by["DAIRY"]["mismatches"] == ["occupation: requires dairy entrepreneur, you have farmer"]
        assert all(v["recommendation_status"] != alt.CONFIRMED_ELIGIBLE for k, v in by.items() if k != "PMFBY")

    def test_profile_signals_never_create_eligibility(self):
        by = self.build("", {"state": "Tamil Nadu", "gender": "female", "land_size_acres": 1.0})["by_scheme"]
        assert by["WEATHER"]["section"] == alt.ALTERNATIVE and by["WEATHER"]["recommendation_status"] != alt.CONFIRMED_ELIGIBLE

    def test_duplicate_by_name_and_flag(self):
        E, U = EligibilityStatus.ELIGIBLE, EligibilityStatus.UNVERIFIABLE
        out = alt.build_sections(
            [res("A_DUP", U), res("A", E, passed=1), res("B", U)],
            [cand("A_DUP", "Kisan Pension Yojana (KPY)"), cand("A", "Kisan Pension Yojana"),
             cand("B", "Other", possible_duplicate=True)], {}, "")
        assert set(out["by_scheme"]) == {"A"}
        assert {d["scheme_id"] for d in out["summary"]["duplicates_hidden"]} == {"A_DUP", "B"}

    def test_empty_inputs(self):
        out = alt.build_sections([], [], None, "")
        assert out["by_scheme"] == {} and out["summary"]["alternatives"] == 0


def test_api_response_carries_sections_and_summary(runs):
    from app.utils.serialization import build_chat_response
    state = runs["mh_cotton_unknown_land"]
    body = build_chat_response({**state, "messages": []}, request_id="t") if "request_id" in \
        build_chat_response.__code__.co_varnames else build_chat_response({**state, "messages": []})
    assert body["recommendation_summary"]["alternatives"] == state["recommendation_sections"]["summary"]["alternatives"]
    assert {s["recommendation_section"] for s in body["schemes"]} <= {alt.ELIGIBLE, alt.ALTERNATIVE, alt.NOT_MATCHING}
    assert "duplicates_hidden" not in body["recommendation_summary"]
