"""
Phase 8: without the LLM, follow-up questions about documents, how to apply and
benefits are answered from the stored scheme data (not just the eligibility list).
"""

from app.agents.response_formatter import _build_detail_section

SCHEMES = [
    {"scheme_id": "PM_KISAN", "name": "Pradhan Mantri Kisan Samman Nidhi", "eligibility_status": "ELIGIBLE",
     "documents": ["Aadhaar Card", "Bank Account Details", "Land Records"],
     "application_steps": ["Visit PM-KISAN portal", "Register with Aadhaar"],
     "benefit_summary": "Rs. 6,000 per year", "official_url": "https://pmkisan.gov.in"},
    {"scheme_id": "KCC", "name": "Kisan Credit Card", "eligibility_status": "ELIGIBLE",
     "documents": [], "application_steps": [], "benefit_summary": None, "official_url": None},
    {"scheme_id": "PM_KMY", "name": "PM Kisan Maandhan", "eligibility_status": "NEEDS_MORE_INFORMATION",
     "documents": ["Aadhaar Card"], "application_steps": [], "benefit_summary": "Pension", "official_url": None},
]


def test_documents_for_referenced_scheme():
    text = _build_detail_section("documents", SCHEMES, "PM_KISAN")
    assert "Documents required for **Pradhan Mantri Kisan Samman Nidhi**" in text
    for doc in ("Aadhaar Card", "Bank Account Details", "Land Records"):
        assert doc in text
    assert "https://pmkisan.gov.in" in text
    assert "Kisan Credit Card" not in text


def test_application_steps_listed_in_order():
    text = _build_detail_section("application_steps", SCHEMES, "PM_KISAN")
    assert text.index("1. Visit PM-KISAN portal") < text.index("2. Register with Aadhaar")


def test_without_reference_uses_eligible_schemes_only():
    text = _build_detail_section("benefits", SCHEMES)
    assert "Rs. 6,000 per year" in text
    assert "PM Kisan Maandhan" not in text            # not eligible -> not listed


def test_missing_data_is_not_invented():
    text = _build_detail_section("documents", SCHEMES, "KCC")
    assert "not available in the scheme database" in text


def test_other_intents_add_nothing():
    assert _build_detail_section("scheme_search", SCHEMES, "PM_KISAN") == ""
    assert _build_detail_section(None, SCHEMES) == ""
    assert _build_detail_section("documents", [], "PM_KISAN") == ""
