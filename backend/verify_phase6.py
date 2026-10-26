"""Quick verification script for Phase 6 modules."""
import sys
sys.path.insert(0, ".")

# 1. Language Registry
from app.localization.languages import (
    LANGUAGE_REGISTRY, get_language_for_frontend, get_sarvam_code,
    resolve_language_code, get_supported_languages, INTERNAL_LANGUAGE,
)
print(f"Language Registry: {len(LANGUAGE_REGISTRY)} languages")
print(f"Frontend items: {len(get_language_for_frontend())}")
print(f"Sarvam code for hi: {get_sarvam_code('hi')}")
print(f"Resolve hi-IN: {resolve_language_code('hi-IN')}")
print(f"Internal: {INTERNAL_LANGUAGE}")

# 2. Language Service
from app.services.language_service import translate_to_internal, translate_from_internal
import asyncio

async def test_passthrough():
    r1 = await translate_to_internal("Hello world", "en")
    assert r1 == "Hello world", f"Passthrough failed: {r1}"
    r2 = await translate_from_internal("Hello world", "en") 
    assert r2 == "Hello world", f"From passthrough failed: {r2}"
    print("Translation passthrough: OK")

asyncio.run(test_passthrough())

# 3. Voice Service
from app.services.voice_service import ASRResult
r = ASRResult(text="test", language="hi-IN")
assert r.text == "test"
print(f"ASRResult model: OK")

# 4. Review Models
from app.models.review import (
    ReviewCase, ReviewStatus, ReviewReason, ReviewAction,
    is_valid_transition, SENSITIVE_FIELDS,
)
case = ReviewCase(session_id="test", query="test query")
assert case.status == ReviewStatus.PENDING
assert is_valid_transition(ReviewStatus.PENDING, ReviewStatus.IN_REVIEW)
assert not is_valid_transition(ReviewStatus.RESOLVED, ReviewStatus.PENDING)
print(f"Review models: OK (transitions validated)")

# 5. Review Service
from app.services.review_service import (
    should_escalate, create_review_case, get_case, resolve_case,
    dismiss_case, get_queue_stats, get_audit_log,
)

class FakeResult:
    status = "UNVERIFIABLE"
    conflicts = []

reason = should_escalate([FakeResult()], [], {})
assert reason == ReviewReason.UNVERIFIABLE
print(f"Escalation trigger: OK (UNVERIFIABLE detected)")

case = create_review_case(
    session_id="verify", query="test",
    reason=ReviewReason.UNVERIFIABLE,
    profile={"state": "KA", "aadhaar_number": "1234"},
    scheme_ids=["s1"], eligibility_results=[], source_conflicts=[],
)
assert "aadhaar_number" not in case.profile_snapshot
print(f"Review case created: {case.case_id} (Aadhaar stripped)")

stats = get_queue_stats()
print(f"Queue stats: {stats}")

# 6. State fields
from app.graph.state import SchemeSetuState
annotations = SchemeSetuState.__annotations__
assert "language" in annotations
assert "needs_review" in annotations
print(f"State fields: OK (language + needs_review present)")

# 7. Request models
from app.models.requests import ChatRequest
req = ChatRequest(message="hello", language="hi")
assert req.language == "hi"
print(f"ChatRequest language: OK")

print("\n=== ALL Phase 6 MODULES VERIFIED ===")
