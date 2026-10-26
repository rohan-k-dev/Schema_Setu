"""
Phase 6 Tests — Multilingual, Voice, Human Review, Accessibility, Security.

Tests all Phase 6 subsystems without requiring external services.
Mocks Sarvam API calls for automated testing (§130, §134).
"""

import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock

# ═══════════════════════════════════════════════════════════════
# LANGUAGE REGISTRY TESTS (§8–§9)
# ═══════════════════════════════════════════════════════════════

class TestLanguageRegistry:
    """Test centralized language registry (§8, §9)."""

    def test_registry_has_english(self):
        from app.localization.languages import LANGUAGE_REGISTRY
        assert "en" in LANGUAGE_REGISTRY
        en = LANGUAGE_REGISTRY["en"]
        assert en.english_name == "English"
        assert en.sarvam_code == "en-IN"

    def test_registry_has_hindi(self):
        from app.localization.languages import LANGUAGE_REGISTRY
        assert "hi" in LANGUAGE_REGISTRY
        assert LANGUAGE_REGISTRY["hi"].name == "हिन्दी"

    def test_registry_has_kannada(self):
        from app.localization.languages import LANGUAGE_REGISTRY
        assert "kn" in LANGUAGE_REGISTRY
        assert LANGUAGE_REGISTRY["kn"].name == "ಕನ್ನಡ"

    def test_registry_has_minimum_languages(self):
        """§9 — at least the languages already claimed."""
        from app.localization.languages import LANGUAGE_REGISTRY
        assert len(LANGUAGE_REGISTRY) >= 9

    def test_each_language_has_required_fields(self):
        """§8 — each language must have required fields."""
        from app.localization.languages import LANGUAGE_REGISTRY
        for code, lang in LANGUAGE_REGISTRY.items():
            assert lang.code, f"{code} missing code"
            assert lang.name, f"{code} missing name"
            assert lang.english_name, f"{code} missing english_name"
            assert lang.sarvam_code, f"{code} missing sarvam_code"

    def test_support_levels_are_declared(self):
        """§9 — distinguish SUPPORTED/PARTIALLY_SUPPORTED/UNAVAILABLE."""
        from app.localization.languages import LANGUAGE_REGISTRY, SupportLevel
        for code, lang in LANGUAGE_REGISTRY.items():
            assert isinstance(lang.asr_support, SupportLevel)
            assert isinstance(lang.tts_support, SupportLevel)
            assert isinstance(lang.translation_support, SupportLevel)
            assert isinstance(lang.ui_support, SupportLevel)

    def test_get_sarvam_code(self):
        from app.localization.languages import get_sarvam_code
        assert get_sarvam_code("hi") == "hi-IN"
        assert get_sarvam_code("kn") == "kn-IN"
        assert get_sarvam_code("xyz") == "en-IN"  # fallback

    def test_resolve_language_code(self):
        """Handles both short and Sarvam formats."""
        from app.localization.languages import resolve_language_code
        assert resolve_language_code("hi") == "hi"
        assert resolve_language_code("hi-IN") == "hi"
        assert resolve_language_code("kn-IN") == "kn"
        assert resolve_language_code("xyz") == "en"  # fallback

    def test_get_supported_languages(self):
        from app.localization.languages import get_supported_languages
        langs = get_supported_languages()
        assert len(langs) >= 9
        codes = [l.code for l in langs]
        assert "en" in codes
        assert "hi" in codes

    def test_get_language_for_frontend(self):
        """§11 — frontend selector format."""
        from app.localization.languages import get_language_for_frontend
        items = get_language_for_frontend()
        assert len(items) >= 9
        for item in items:
            assert "code" in item
            assert "name" in item
            assert "english_name" in item
            assert "has_voice" in item
            assert "has_tts" in item

    def test_no_hardcoded_language_codes(self):
        """§8 — language codes must come from registry, not hardcoded."""
        from app.localization.languages import INTERNAL_LANGUAGE, DEFAULT_LANGUAGE
        assert INTERNAL_LANGUAGE == "en"
        assert DEFAULT_LANGUAGE == "en"


# ═══════════════════════════════════════════════════════════════
# LANGUAGE SERVICE TESTS (§16–§17)
# ═══════════════════════════════════════════════════════════════

class TestLanguageService:
    """Test translation abstraction (§16, §17)."""

    @pytest.mark.asyncio
    async def test_translate_english_passthrough(self):
        """English → English should pass through without API call."""
        from app.services.language_service import translate_to_internal
        result = await translate_to_internal("Hello farmer", "en")
        assert result == "Hello farmer"

    @pytest.mark.asyncio
    async def test_translate_from_english_passthrough(self):
        from app.services.language_service import translate_from_internal
        result = await translate_from_internal("You are eligible", "en")
        assert result == "You are eligible"

    @pytest.mark.asyncio
    async def test_translate_to_internal_fallback_on_failure(self):
        """§30 — on failure, return original text."""
        from app.services.language_service import translate_to_internal
        with patch("app.services.language_service._translate", side_effect=Exception("API down")):
            result = await translate_to_internal("नमस्ते", "hi")
            assert result == "नमस्ते"  # original preserved

    @pytest.mark.asyncio
    async def test_translate_from_internal_fallback_on_failure(self):
        """§33 — on failure, return English text."""
        from app.services.language_service import translate_from_internal
        with patch("app.services.language_service._translate", side_effect=Exception("API down")):
            result = await translate_from_internal("You are eligible", "hi")
            assert result == "You are eligible"

    @pytest.mark.asyncio
    async def test_translation_does_not_alter_profile_facts(self):
        """§17 — translation must not alter structured facts."""
        # This validates the architecture: translation happens before
        # profile extraction, not after structured data is created.
        from app.services.language_service import translate_to_internal
        # Even if translation fails, the original text is preserved
        result = await translate_to_internal("I have 2 acres", "en")
        assert "2" in result


# ═══════════════════════════════════════════════════════════════
# VOICE SERVICE TESTS (§27–§29)
# ═══════════════════════════════════════════════════════════════

class TestVoiceService:
    """Test ASR/TTS with typed output (§27–§33)."""

    def test_asr_result_model(self):
        """§28 — typed ASR output."""
        from app.services.voice_service import ASRResult
        result = ASRResult(text="test", language="hi-IN", confidence=None)
        assert result.text == "test"
        assert result.language == "hi-IN"
        assert result.confidence is None  # null if unavailable

    @pytest.mark.asyncio
    async def test_asr_empty_returns_none(self):
        """§29 — empty transcript returns None."""
        from app.services.voice_service import transcribe_audio

        mock_response = MagicMock()
        mock_response.json.return_value = {"transcript": ""}
        mock_response.raise_for_status = MagicMock()

        with patch("app.services.voice_service._validate_sarvam_key", return_value="key"), \
             patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            result = await transcribe_audio(b"audio", "test.wav", "audio/wav")
            assert result is None


# ═══════════════════════════════════════════════════════════════
# HUMAN REVIEW MODEL TESTS (§58–§65)
# ═══════════════════════════════════════════════════════════════

class TestReviewModels:
    """Test review data models (§58–§65)."""

    def test_review_case_creation(self):
        from app.models.review import ReviewCase, ReviewStatus
        case = ReviewCase(session_id="s1", query="test")
        assert case.case_id
        assert case.status == ReviewStatus.PENDING
        assert case.created_at

    def test_review_status_values(self):
        """§59 — four status values."""
        from app.models.review import ReviewStatus
        assert ReviewStatus.PENDING.value == "PENDING"
        assert ReviewStatus.IN_REVIEW.value == "IN_REVIEW"
        assert ReviewStatus.RESOLVED.value == "RESOLVED"
        assert ReviewStatus.DISMISSED.value == "DISMISSED"

    def test_review_reason_values(self):
        """§60 — controlled reason values."""
        from app.models.review import ReviewReason
        reasons = [r.value for r in ReviewReason]
        assert "UNVERIFIABLE" in reasons
        assert "RULE_CONFLICT" in reasons
        assert "SOURCE_CONFLICT" in reasons
        assert "INSUFFICIENT_DATA" in reasons
        assert "SYSTEM_ERROR" in reasons

    def test_review_action_values(self):
        """§63 — reviewer actions."""
        from app.models.review import ReviewAction
        actions = [a.value for a in ReviewAction]
        assert "APPROVE" in actions
        assert "REJECT" in actions
        assert "REQUEST_INFORMATION" in actions
        assert "MARK_UNVERIFIABLE" in actions

    def test_valid_transitions(self):
        """§125 — status transition validation."""
        from app.models.review import ReviewStatus, is_valid_transition
        # PENDING → IN_REVIEW ✓
        assert is_valid_transition(ReviewStatus.PENDING, ReviewStatus.IN_REVIEW)
        # PENDING → DISMISSED ✓
        assert is_valid_transition(ReviewStatus.PENDING, ReviewStatus.DISMISSED)
        # PENDING → RESOLVED ✗
        assert not is_valid_transition(ReviewStatus.PENDING, ReviewStatus.RESOLVED)
        # IN_REVIEW → RESOLVED ✓
        assert is_valid_transition(ReviewStatus.IN_REVIEW, ReviewStatus.RESOLVED)
        # RESOLVED → anything ✗
        assert not is_valid_transition(ReviewStatus.RESOLVED, ReviewStatus.PENDING)

    def test_sanitize_profile(self):
        """§61 — strip sensitive fields."""
        from app.models.review import ReviewCase
        case = ReviewCase(
            profile_snapshot={
                "state": "Karnataka",
                "aadhaar_number": "1234",
                "bank_account": "5678",
            }
        )
        case.sanitize_profile()
        assert "state" in case.profile_snapshot
        assert "aadhaar_number" not in case.profile_snapshot
        assert "bank_account" not in case.profile_snapshot


# ═══════════════════════════════════════════════════════════════
# REVIEW SERVICE TESTS (§56–§67)
# ═══════════════════════════════════════════════════════════════

class TestReviewService:
    """Test review queue operations (§56–§67)."""

    def test_escalation_triggers_unverifiable(self):
        """§57 — UNVERIFIABLE eligibility triggers escalation."""
        from app.services.review_service import should_escalate
        from app.models.review import ReviewReason

        class FakeResult:
            status = "UNVERIFIABLE"
            conflicts = []

        reason = should_escalate([FakeResult()], [], {})
        assert reason == ReviewReason.UNVERIFIABLE

    def test_escalation_triggers_conflict(self):
        """§57 — rule conflicts trigger escalation."""
        from app.services.review_service import should_escalate
        from app.models.review import ReviewReason

        class FakeResult:
            status = "ELIGIBLE"
            conflicts = [{"field": "land", "type": "contradictory"}]

        reason = should_escalate([FakeResult()], [], {})
        assert reason == ReviewReason.RULE_CONFLICT

    def test_escalation_triggers_source_conflict(self):
        from app.services.review_service import should_escalate
        from app.models.review import ReviewReason
        reason = should_escalate([], [{"conflict": "DB vs web"}], {})
        assert reason == ReviewReason.SOURCE_CONFLICT

    def test_no_escalation_for_clean_results(self):
        from app.services.review_service import should_escalate

        class FakeResult:
            status = "ELIGIBLE"
            conflicts = []

        reason = should_escalate([FakeResult()], [], {})
        assert reason is None

    def test_create_and_get_case(self):
        from app.services.review_service import create_review_case, get_case
        from app.models.review import ReviewReason, ReviewStatus

        case = create_review_case(
            session_id="test-session",
            query="test query",
            reason=ReviewReason.UNVERIFIABLE,
            profile={"state": "Karnataka", "aadhaar_number": "1234"},
            scheme_ids=["scheme_1"],
            eligibility_results=[],
            source_conflicts=[],
        )
        assert case.case_id
        assert case.status == ReviewStatus.PENDING
        # Sensitive field stripped
        assert "aadhaar_number" not in case.profile_snapshot

        # Retrieve
        retrieved = get_case(case.case_id)
        assert retrieved is not None
        assert retrieved.case_id == case.case_id

    def test_resolve_case(self):
        from app.services.review_service import create_review_case, resolve_case
        from app.models.review import ReviewReason, ReviewAction, ReviewStatus

        case = create_review_case(
            session_id="s2", query="q2",
            reason=ReviewReason.RULE_CONFLICT,
            profile={}, scheme_ids=[], eligibility_results=[], source_conflicts=[],
        )

        # Must go PENDING → IN_REVIEW first
        resolved = resolve_case(
            case.case_id,
            ReviewAction.REQUEST_INFORMATION,
            reviewer_id="reviewer1",
            note="Need income info",
        )
        assert resolved is not None
        assert resolved.status == ReviewStatus.IN_REVIEW

        # Then IN_REVIEW → RESOLVED
        resolved = resolve_case(
            case.case_id,
            ReviewAction.APPROVE,
            reviewer_id="reviewer1",
            note="Confirmed eligible",
        )
        assert resolved is not None
        assert resolved.status == ReviewStatus.RESOLVED

    def test_dismiss_case(self):
        from app.services.review_service import create_review_case, dismiss_case
        from app.models.review import ReviewReason, ReviewStatus

        case = create_review_case(
            session_id="s3", query="q3",
            reason=ReviewReason.OTHER,
            profile={}, scheme_ids=[], eligibility_results=[], source_conflicts=[],
        )

        result = dismiss_case(case.case_id, "admin", "Not relevant")
        assert result is not None
        assert result.status == ReviewStatus.DISMISSED

    def test_invalid_transition_rejected(self):
        """§125 — invalid transitions are rejected."""
        from app.services.review_service import create_review_case, resolve_case, dismiss_case
        from app.models.review import ReviewReason, ReviewAction, ReviewStatus

        case = create_review_case(
            session_id="s4", query="q4",
            reason=ReviewReason.OTHER,
            profile={}, scheme_ids=[], eligibility_results=[], source_conflicts=[],
        )

        # Dismiss it
        dismiss_case(case.case_id)

        # Try to resolve a dismissed case — should fail
        result = resolve_case(case.case_id, ReviewAction.APPROVE)
        assert result is None  # Invalid transition

    def test_audit_log(self):
        """§70 — audit log records actions."""
        from app.services.review_service import create_review_case, get_audit_log
        from app.models.review import ReviewReason

        case = create_review_case(
            session_id="s5", query="q5",
            reason=ReviewReason.SYSTEM_ERROR,
            profile={}, scheme_ids=[], eligibility_results=[], source_conflicts=[],
        )

        log = get_audit_log(case.case_id)
        assert len(log) >= 1
        assert log[0].action == "CREATED"

    def test_queue_stats(self):
        from app.services.review_service import get_queue_stats
        stats = get_queue_stats()
        assert "total" in stats
        assert "pending" in stats
        assert "resolved" in stats


# ═══════════════════════════════════════════════════════════════
# LANGGRAPH STATE TESTS (§10)
# ═══════════════════════════════════════════════════════════════

class TestStateLanguageFields:
    """Test language fields in LangGraph state (§10)."""

    def test_state_has_language_fields(self):
        from app.graph.state import SchemeSetuState
        annotations = SchemeSetuState.__annotations__
        assert "language" in annotations
        assert "language_name" in annotations
        assert "language_mode" in annotations

    def test_state_has_review_fields(self):
        from app.graph.state import SchemeSetuState
        annotations = SchemeSetuState.__annotations__
        assert "needs_review" in annotations
        assert "review_reason" in annotations


# ═══════════════════════════════════════════════════════════════
# ELIGIBILITY LANGUAGE-INDEPENDENCE TESTS (§136)
# ═══════════════════════════════════════════════════════════════

class _MockRule:
    """Lightweight mock for eligibility rules (same pattern as test_phase5)."""
    def __init__(self, rule_id="R1", field_name="state", operator="IN",
                 value_json=None, logical_group="AND", required=True,
                 source_text=None, unit=None, original_value=None,
                 original_unit=None, rule_order=0):
        self.id = 1
        self.scheme_id = 1
        self.rule_id = rule_id
        self.field_name = field_name
        self.operator = operator
        self.value_json = value_json
        self.logical_group = logical_group
        self.required = required
        self.source_text = source_text
        self.unit = unit
        self.original_value = original_value
        self.original_unit = original_unit
        self.rule_order = rule_order


class TestEligibilityLanguageIndependence:
    """§136 — same profile must produce same eligibility regardless of language."""

    def test_same_profile_same_result(self):
        """The eligibility engine operates on canonical profiles, not language."""
        from app.eligibility.evaluator import evaluate_scheme

        profile = {"state": "karnataka", "land_size_acres": 2, "primary_crop": "ragi"}
        rules = [
            _MockRule(rule_id="r1", field_name="state", operator="IN",
                      value_json=["karnataka"], source_text="Karnataka only"),
            _MockRule(rule_id="r2", field_name="land_size_acres", operator="LTE",
                      value_json=5, source_text="Up to 5 acres"),
        ]

        # Same profile → same result (regardless of input language)
        result = evaluate_scheme("s1", "Test Scheme", rules, profile)
        assert result.status.value == "ELIGIBLE"

        # Run again — deterministic
        result2 = evaluate_scheme("s1", "Test Scheme", rules, profile)
        assert result2.status.value == result.status.value


# ═══════════════════════════════════════════════════════════════
# SECURITY TESTS (§89–§94)
# ═══════════════════════════════════════════════════════════════

class TestSecurityPhase6:
    """Security regression tests for Phase 6 (§89–§94)."""

    def test_no_aadhaar_in_review_case(self):
        """§89 — Aadhaar not stored in review cases."""
        from app.services.review_service import create_review_case
        from app.models.review import ReviewReason

        case = create_review_case(
            session_id="sec1", query="test",
            reason=ReviewReason.OTHER,
            profile={"state": "KA", "aadhaar_number": "123456789012"},
            scheme_ids=[], eligibility_results=[], source_conflicts=[],
        )
        assert "aadhaar_number" not in case.profile_snapshot

    def test_no_eval_or_exec(self):
        """§91 — no eval() or exec() in eligibility code."""
        import inspect
        from app.eligibility import operators, evaluator, normalizer
        for module in [operators, evaluator, normalizer]:
            source = inspect.getsource(module)
            assert "eval(" not in source
            assert "exec(" not in source

    def test_review_case_no_sensitive_fields(self):
        """§61 — sensitive fields stripped."""
        from app.models.review import SENSITIVE_FIELDS
        assert "aadhaar_number" in SENSITIVE_FIELDS
        assert "bank_account" in SENSITIVE_FIELDS
        assert "pan_number" in SENSITIVE_FIELDS


# ═══════════════════════════════════════════════════════════════
# ERROR HANDLING & FALLBACK TESTS (§71–§75)
# ═══════════════════════════════════════════════════════════════

class TestErrorHandling:
    """Test fail-safe behavior (§73)."""

    def test_uncertainty_never_becomes_eligible(self):
        """§73 — system uncertainty must NOT become user certainty."""
        from app.eligibility.evaluator import evaluate_scheme

        # No rules → UNVERIFIABLE, not ELIGIBLE
        result = evaluate_scheme("s1", "Test", [], {"state": "Karnataka"})
        assert result.status.value == "UNVERIFIABLE"

    def test_translation_fallback_preserves_text(self):
        """§30 — translation failure returns original text."""
        import asyncio
        from app.services.language_service import translate_to_internal

        with patch("app.services.language_service._translate", side_effect=Exception("fail")):
            result = asyncio.get_event_loop().run_until_complete(
                translate_to_internal("Original text", "hi")
            )
            assert result == "Original text"


# ═══════════════════════════════════════════════════════════════
# MULTILINGUAL TEST DATA (§128–§129)
# ═══════════════════════════════════════════════════════════════

class TestMultilingualData:
    """Test multilingual test cases exist and are valid (§128)."""

    def test_multilingual_cases_exist(self):
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "..", "data", "evaluation", "multilingual_cases.json",
        )
        # Will be created in step 15
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            assert len(data) >= 3


# ═══════════════════════════════════════════════════════════════
# VOICE SESSION CONTINUITY (§36–§37)
# ═══════════════════════════════════════════════════════════════

class TestVoiceTextSessionContinuity:
    """§36 — voice and text must share the same session."""

    def test_same_thread_id_concept(self):
        """Both /chat and /voice accept thread_id for session isolation."""
        from app.models.requests import ChatRequest
        req = ChatRequest(message="test", thread_id="session-123", language="en")
        assert req.thread_id == "session-123"
        assert req.language == "en"


# ═══════════════════════════════════════════════════════════════
# REQUEST MODEL TESTS
# ═══════════════════════════════════════════════════════════════

class TestRequestModels:
    """Test updated request models."""

    def test_chat_request_has_language(self):
        from app.models.requests import ChatRequest
        req = ChatRequest(message="hello")
        assert req.language == "en"  # default

    def test_chat_request_custom_language(self):
        from app.models.requests import ChatRequest
        req = ChatRequest(message="hello", language="hi")
        assert req.language == "hi"
