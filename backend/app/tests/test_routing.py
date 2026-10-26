"""
Tests for routing logic and completeness checking — Phase 4.

No external dependencies — tests pure functions.
"""

import pytest
from app.graph.routing import route_based_on_completeness, route_after_completeness, route_after_query_rewrite


class TestRoutingLogic:
    """Test deterministic routing based on missing fields."""

    def test_route_to_question_when_fields_missing(self):
        """When fields are missing, route to question_agent."""
        state = {"missing_fields": ["state", "land_size_acres"], "profile_complete": False}
        result = route_after_completeness(state)
        assert result == "question_agent"

    def test_route_to_query_rewriter_when_complete(self):
        """When no fields are missing, route to query_rewriter."""
        state = {"missing_fields": [], "profile_complete": True}
        result = route_after_completeness(state)
        assert result == "query_rewriter"

    def test_route_with_no_missing_fields_key(self):
        """When missing_fields key is absent but profile_complete is True, route to query_rewriter."""
        state = {"profile_complete": True}
        result = route_after_completeness(state)
        assert result == "query_rewriter"

    def test_route_with_single_missing_field(self):
        """Even one missing field should route to question_agent."""
        state = {"missing_fields": ["primary_crop"], "profile_complete": False}
        result = route_after_completeness(state)
        assert result == "question_agent"

    def test_route_with_profile_conflict(self):
        """Profile conflicts should route to question_agent for confirmation."""
        state = {
            "missing_fields": [],
            "profile_complete": True,
            "profile_conflicts": [{"field": "land_size_acres", "old_value": 2, "new_value": 10}],
        }
        result = route_after_completeness(state)
        assert result == "question_agent"

    def test_backward_compatible_routing(self):
        """Legacy route_based_on_completeness still works."""
        state = {"missing_fields": ["state"], "profile_complete": False}
        result = route_based_on_completeness(state)
        assert result == "question_agent"


class TestQueryRewriteRouting:
    """Test routing after query rewriting."""

    def test_route_to_retrieval(self):
        """Normal query routes to retrieval_agent."""
        state = {"needs_clarification": False}
        result = route_after_query_rewrite(state)
        assert result == "retrieval_agent"

    def test_route_to_question_when_ambiguous(self):
        """Ambiguous query routes to question_agent for clarification."""
        state = {"needs_clarification": True}
        result = route_after_query_rewrite(state)
        assert result == "question_agent"
