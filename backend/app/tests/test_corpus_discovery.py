"""
scripts/discover_missing_schemes.py — candidate records for genuinely missing schemes are built only
from what an official page states (saved fixture pages, no network): no invented fields or rules,
duplicates / components of existing schemes skipped, governance clauses never taken as benefits.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import discover_missing_schemes as dms  # noqa: E402

from app.ingestion import CanonicalScheme  # noqa: E402
from app.live.extractor import extract  # noqa: E402
from app.live.sources import Registry  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "live"
CORPUS = json.loads((ROOT / "data" / "validated" / "schemes.json").read_text(encoding="utf-8"))


def page(name, url):
    html = (FIX / name).read_text(encoding="utf-8")
    reg = Registry()
    fr = SimpleNamespace(final_url=url, host=reg.classify(url).host, content_hash="h" * 64)
    return fr, extract(html=html, base_url=url, official_host_check=lambda u: reg.classify(u).official)


def test_record_holds_only_what_the_page_states():
    fr, ex = page("state_scheme.html", "https://raitamitra.karnataka.gov.in/raitha-siri")
    rec = dms.build_record(("NEW_KA", ["raitha"], fr.final_url, "state", "Karnataka"), fr, ex, "2026-10-26")
    CanonicalScheme(**rec)                                              # valid for the corpus / pipeline
    assert rec["eligibility_rules"] == [] and rec["needs_review"] is True
    assert rec["applicable_states"] == ["Karnataka"] and rec["application_url"] == "https://fruits.karnataka.gov.in/apply"
    assert rec["benefits"][0]["description"].startswith("Financial assistance of Rs. 10,000 per hectare")
    assert all(b["amount"] is None for b in rec["benefits"])            # amounts stay in the quoted text
    assert rec["source_records"][0]["url"] == fr.final_url and rec["source_records"][0]["retrieved_at"] == "2026-10-26"
    assert "inferred" in rec["review_notes"] and "No structured eligibility rules" in rec["review_notes"]
    assert rec["aadhaar_requirement"] == "unknown" and rec["scheme_type"] is None


def test_missing_fields_stay_empty():
    fr, ex = page("ministry_pmkisan.html", "https://pmkisan.gov.in/")
    rec = dms.build_record(("X", ["kisan"], fr.final_url, "central", None), fr, ex, "2026-10-26")
    assert rec["application_steps"] == [] or all(s["description"] for s in rec["application_steps"])
    page_text = (FIX / "ministry_pmkisan.html").read_text(encoding="utf-8")
    assert all(x.rstrip(".") in page_text for x in rec["exclusions"])          # quoted from the page
    assert rec["applicable_states"] is None
    assert rec["ministry"] is None or rec["ministry"] in page_text


@pytest.mark.parametrize("line,keep", [
    ("5.3.2 The Steering Committee will examine and approve the Projects", False),
    ("x. Joint Secretary, NRM/RFS, DA&FW Member Secretary", False),
    ("55% subsidy for small and marginal farmers on drip systems", True),
    ("Financial assistance of Rs. 10,000 per hectare", True),
])
def test_governance_clauses_are_not_benefits(line, keep):
    assert (dms.benefit_lines([line]) == [line]) is keep


def test_existing_schemes_and_components_are_duplicates():
    ids, urls, names, aliases = dms.corpus_index(CORPUS)
    assert dms.existing_match({"name": "PDMC - Micro Irrigation", "description": "Per Drop More Crop - Micro Irrigation"},
                              aliases)[0] == "PMKSY"
    assert dms.existing_match({"name": "Kisan Credit Card", "description": ""}, aliases)[0] == "KCC"
    assert dms.existing_match({"name": "Pradhan Mantri Matsya Sampada Yojana", "description": "fisheries"}, aliases) is None
    assert "PM_KISAN" in ids and any("pmkisan.gov.in" in u for u in urls)


def test_seeds_are_official_and_unique():
    reg = Registry()
    assert len({s[0] for s in dms.SEEDS}) == len(dms.SEEDS)
    assert all(reg.classify(s[2]).official for s in dms.SEEDS)
    assert not {s[0] for s in dms.SEEDS} & {s["scheme_id"] for s in CORPUS}
