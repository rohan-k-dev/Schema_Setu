"""
Tests for serialization utilities.

Tests response building and message extraction without external dependencies.
"""

import pytest
from app.utils.serialization import extract_latest_ai_message, build_chat_response


class TestExtractLatestAiMessage:
    """Test message extraction from various formats."""

    def test_empty_messages(self):
        """Empty message list should return None."""
        result = extract_latest_ai_message([])
        assert result is None

    def test_tuple_format_assistant(self):
        """Should extract from ('assistant', 'text') tuple."""
        messages = [("assistant", "What state are you from?")]
        result = extract_latest_ai_message(messages)
        assert result == "What state are you from?"

    def test_tuple_format_ai(self):
        """Should extract from ('ai', 'text') tuple."""
        messages = [("ai", "Tell me about your land.")]
        result = extract_latest_ai_message(messages)
        assert result == "Tell me about your land."

    def test_latest_message_extracted(self):
        """Should extract the LAST AI message when multiple exist."""
        messages = [
            ("assistant", "First question"),
            ("assistant", "Second question"),
        ]
        result = extract_latest_ai_message(messages)
        assert result == "Second question"

    def test_no_ai_message(self):
        """Should return None if no AI messages exist."""
        messages = [("user", "Hello")]
        result = extract_latest_ai_message(messages)
        assert result is None


class TestBuildChatResponse:
    """Test response building from LangGraph state."""

    def test_asking_question_response(self):
        """Should build asking_question response when AI message exists."""

        class MockMsg:
            type = "ai"
            content = "What is your state?"

        state = {
            "messages": [MockMsg()],
            "recommended_schemes": [],
            "profile": {"state": "Karnataka"},
        }
        result = build_chat_response(state, request_id="test123")
        assert result["status"] == "asking_question"
        assert result["reply"] == "What is your state?"
        assert result["request_id"] == "test123"

    def test_schemes_found_response(self):
        """Should build schemes_found response when schemes exist."""
        state = {
            "messages": [],
            "recommended_schemes": [{"scheme_name": "PM-Kisan"}],
            "profile": {"state": "Karnataka"},
        }
        result = build_chat_response(state, request_id="test456")
        assert result["status"] == "schemes_found"
        assert len(result["schemes"]) == 1

    def test_error_response_when_empty(self):
        """Should build error response when no messages or schemes."""
        state = {
            "messages": [],
            "recommended_schemes": [],
            "profile": None,
        }
        result = build_chat_response(state)
        assert result["status"] == "error"

    def test_voice_transcript_included(self):
        """Should include user_transcript for voice responses."""
        state = {
            "messages": [("assistant", "Hello")],
            "recommended_schemes": [],
            "profile": None,
        }
        result = build_chat_response(state, user_transcript="I am from Karnataka")
        assert result["user_transcript"] == "I am from Karnataka"
