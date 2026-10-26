"""
Grounding validator: bold headings are not scheme names, made-up scheme names are still rejected.

A live reply on 2026-10-26 was discarded because "**Scheme Search – Dairy cattle farmers in Telangana with
3 acres**" was read as an unknown scheme name (app/xai/response_validator.py). Real scheme names keep being
checked part by part, so an invented name can't hide inside a heading.
"""

from __future__ import annotations

import pytest

from app.xai.response_validator import validate_llm_response

SCHEMES = [
    {"scheme_id": "PM_KISAN", "name": "Pradhan Mantri Kisan Samman Nidhi", "eligibility_status": "ELIGIBLE"},
    {"scheme_id": "NLM", "name": "National Livestock Mission", "eligibility_status": "UNVERIFIABLE"},
    {"scheme_id": "STATE_KA_KRUSHAK", "name": "Raitha Siri - Karnataka Farmer Income Support",
     "eligibility_status": "ELIGIBLE"},
    {"scheme_id": "NRLM", "name": "Deendayal Antyodaya Yojana - National Rural Livelihoods Mission",
     "eligibility_status": "UNVERIFIABLE"},
    {"scheme_id": "PM_KMY", "name": "Pradhan Mantri Kisan Maandhan Yojana", "eligibility_status": "ELIGIBLE"},
]


@pytest.mark.parametrize("heading", [
    "**Scheme Search – Dairy cattle farmers in Telangana with 3 acres**",     # the live reply
    "**Scheme Search - Dairy cattle farmers in Telangana**",
    "**Scheme Summary: what matches your details**",
    "**Scheme Recommendations for You**",
    "**Other relevant schemes**",
    "**Schemes that need more information**",
    "**Eligible Schemes | Karnataka, ragi, 2 acres**",
])
def test_generic_headings_are_not_scheme_names(heading):
    text = f"{heading}\n- **Pradhan Mantri Kisan Samman Nidhi**: matches the criteria we hold."
    ok, reasons = validate_llm_response(text, SCHEMES)
    assert ok, reasons


@pytest.mark.parametrize("name", [
    "**Pradhan Mantri Kisan Samman Nidhi**",
    "**National Livestock Mission**",
    "**Raitha Siri - Karnataka Farmer Income Support**",            # a real name containing " - "
    "**Deendayal Antyodaya Yojana - National Rural Livelihoods Mission**",
    "**Pradhan Mantri Kisan Maandhan Yojana: pension at 60**",       # real name + description
])
def test_real_scheme_names_still_accepted(name):
    ok, reasons = validate_llm_response(f"You can look at {name}.", SCHEMES)
    assert ok, reasons


@pytest.mark.parametrize("bad", [
    "**Kisan Gold Bonus Scheme**",
    "**Scheme Search – Kisan Samridhi Yojana**",                     # made-up name inside a heading
    "**Dairy Support: Gau Palan Mission for Telangana**",
    "**Krishi Sahay Card | apply online**",
    "**Fake Kisan Yojana and other schemes**",                       # plural no longer hides a name
    "**PM Krishi Bonus Scheme – for farmers in Telangana**",
])
def test_invented_scheme_names_still_rejected(bad):
    ok, reasons = validate_llm_response(f"You can also apply for {bad}.", SCHEMES)
    assert not ok and any("unknown scheme name" in r for r in reasons), reasons


def test_other_grounding_rules_unchanged():
    ok, reasons = validate_llm_response("**Scheme Search – Telangana**\nYou are eligible for "
                                        "**National Livestock Mission**.", SCHEMES)
    assert not ok and any("claims eligibility for NLM" in r for r in reasons)
    ok, reasons = validate_llm_response("**Scheme Summary**: PM-KISAN pays Rs. 9,999 per year.", SCHEMES)
    assert not ok and any("unsupported amount" in r for r in reasons)
