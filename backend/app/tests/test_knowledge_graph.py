"""
Phase 3 Tests — Knowledge Graph construction, validation, and query.

All tests use in-memory fixtures — NO database or network required.
"""

import json
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.knowledge_graph.schema import (
    NodeType, EdgeType, make_scheme_id, make_state_id, make_crop_id,
    make_beneficiary_id, make_category_id, make_ministry_id,
    make_document_id, make_rule_id, make_district_id, make_country_id,
    should_skip_value, _normalize_for_id,
)
from app.knowledge_graph.builder import KnowledgeGraphBuilder
from app.knowledge_graph.serializer import (
    graph_to_json, json_to_graph, compute_graph_hash, save_graph_snapshot,
    load_graph_snapshot,
)
from app.knowledge_graph.validator import validate_graph, calculate_coverage_metrics
from app.knowledge_graph.repository import KnowledgeGraphRepository, GraphCandidate


# ─── Test Fixtures ───────────────────────────────────────────

SAMPLE_SCHEMES = [
    {
        "scheme_id": "TEST_SCHEME_001",
        "name": "Test Agriculture Scheme",
        "description": "A central test scheme.",
        "ministry": "Ministry of Agriculture",
        "level": "central",
        "status": "ACTIVE",
        "eligibility_summary": "All farmers with land <= 5 acres",
        "applicable_states": None,  # Central — all states
        "applicable_crops": None,
        "target_beneficiaries": ["farmers", "small farmers"],
        "benefits": [{"type": "financial_assistance", "description": "Rs. 6000/year"}],
        "eligibility_rules": [
            {"field": "land_size_acres", "operator": "LTE", "value": 5,
             "logical_group": "AND", "required": True, "source_text": "Land <= 5 acres"}
        ],
        "required_documents": [{"name": "Aadhaar Card", "mandatory": True}],
        "source_records": [
            {"source_id": "SRC_001", "source_type": "OFFICIAL_CENTRAL", "url": "https://test.gov.in"}
        ],
    },
    {
        "scheme_id": "TEST_SCHEME_002",
        "name": "Karnataka Ragi Scheme",
        "description": "State-specific scheme for Karnataka.",
        "ministry": "State Agriculture Dept",
        "level": "state",
        "status": "ACTIVE",
        "eligibility_summary": "Karnataka farmers growing ragi",
        "applicable_states": ["Karnataka"],
        "applicable_crops": ["ragi", "finger millet"],
        "target_beneficiaries": ["farmers"],
        "benefits": [{"type": "subsidy", "description": "Seed subsidy"}],
        "eligibility_rules": [
            {"field": "state", "operator": "EQ", "value": "Karnataka",
             "logical_group": "AND", "required": True},
            {"field": "category", "operator": "IN", "value": ["SC", "ST"],
             "logical_group": "OR", "required": False}
        ],
        "required_documents": [
            {"name": "Land Record", "mandatory": True},
            {"name": "Aadhaar Card", "mandatory": True}
        ],
        "source_records": [
            {"source_id": "SRC_002", "source_type": "OFFICIAL_STATE"}
        ],
    },
    {
        "scheme_id": "TEST_SCHEME_003",
        "name": "Crop Insurance Test",
        "description": "Insurance for specific crops.",
        "level": "central",
        "status": "ACTIVE",
        "applicable_states": ["Karnataka", "Maharashtra"],
        "applicable_crops": ["rice", "wheat"],
        "target_beneficiaries": ["farmers"],
        "benefits": [{"type": "insurance", "description": "Crop insurance"}],
        "eligibility_rules": [],
        "required_documents": [],
        "source_records": [
            {"source_id": "SRC_003", "source_type": "OFFICIAL_CENTRAL"}
        ],
    },
]


def _build_test_graph():
    """Build a graph from test fixtures."""
    builder = KnowledgeGraphBuilder()
    graph = builder.build_from_corpus(SAMPLE_SCHEMES, corpus_version="1.0.0")
    return graph, builder.get_stats(), builder.get_warnings()


# ─── Node ID Tests ───────────────────────────────────────────

class TestNodeIDs:
    def test_scheme_id(self):
        assert make_scheme_id("PM_KISAN") == "SCHEME:PM_KISAN"

    def test_state_id(self):
        assert make_state_id("Karnataka") == "STATE:KARNATAKA"

    def test_state_id_normalization(self):
        assert make_state_id("Andhra Pradesh") == "STATE:ANDHRA_PRADESH"

    def test_crop_id(self):
        assert make_crop_id("ragi") == "CROP:RAGI"

    def test_district_id_namespaced(self):
        assert make_district_id("Karnataka", "Mandya") == "DISTRICT:KARNATAKA:MANDYA"

    def test_ministry_id(self):
        result = make_ministry_id("Ministry of Agriculture")
        assert result == "MINISTRY:MINISTRY_OF_AGRICULTURE"

    def test_document_id(self):
        assert make_document_id("Aadhaar Card") == "DOCUMENT:AADHAAR_CARD"

    def test_rule_id_with_explicit_id(self):
        assert make_rule_id("PM_KISAN", 0, "RULE_001") == "ELIGIBILITY_RULE:RULE_001"

    def test_rule_id_auto_generated(self):
        assert make_rule_id("PM_KISAN", 0) == "ELIGIBILITY_RULE:PM_KISAN_0"

    def test_country_id(self):
        assert make_country_id("INDIA") == "COUNTRY:INDIA"


# ─── Skip Value Tests ────────────────────────────────────────

class TestSkipValues:
    def test_unknown_skipped(self):
        assert should_skip_value("unknown") is True

    def test_empty_skipped(self):
        assert should_skip_value("") is True

    def test_none_skipped(self):
        assert should_skip_value(None) is True

    def test_valid_not_skipped(self):
        assert should_skip_value("Karnataka") is False


# ─── Graph Build Tests ───────────────────────────────────────

class TestGraphBuild:
    def test_graph_has_nodes(self):
        graph, stats, _ = _build_test_graph()
        assert stats["total_nodes"] > 0

    def test_graph_has_edges(self):
        graph, stats, _ = _build_test_graph()
        assert stats["total_edges"] > 0

    def test_scheme_nodes_created(self):
        graph, stats, _ = _build_test_graph()
        scheme_count = stats["node_type_counts"].get("SCHEME", 0)
        assert scheme_count == 3

    def test_country_node_created(self):
        graph, _, _ = _build_test_graph()
        assert make_country_id("INDIA") in graph

    def test_state_nodes_created(self):
        graph, stats, _ = _build_test_graph()
        state_count = stats["node_type_counts"].get("STATE", 0)
        assert state_count >= 1  # At least Karnataka

    def test_crop_nodes_created(self):
        graph, stats, _ = _build_test_graph()
        crop_count = stats["node_type_counts"].get("CROP", 0)
        assert crop_count >= 2  # ragi, finger millet, rice, wheat

    def test_central_scheme_has_global_applicability(self):
        graph, _, _ = _build_test_graph()
        scheme_node = make_scheme_id("TEST_SCHEME_001")
        country_node = make_country_id("INDIA")
        assert graph.has_edge(scheme_node, country_node)

    def test_state_scheme_has_state_edge(self):
        graph, _, _ = _build_test_graph()
        scheme_node = make_scheme_id("TEST_SCHEME_002")
        state_node = make_state_id("Karnataka")
        assert graph.has_edge(scheme_node, state_node)

    def test_no_central_scheme_all_states(self):
        """Central schemes must NOT have edges to every state (§84)."""
        graph, _, _ = _build_test_graph()
        scheme_node = make_scheme_id("TEST_SCHEME_001")
        state_edges = [
            tgt for _, tgt, attrs in graph.out_edges(scheme_node, data=True)
            if attrs.get("relation") == EdgeType.APPLIES_TO_STATE.value
        ]
        assert len(state_edges) == 0  # Central scheme → COUNTRY:INDIA, not individual states

    def test_ministry_reuse(self):
        """Multiple schemes pointing to same ministry should share node (§20)."""
        graph, stats, _ = _build_test_graph()
        # Both scheme 1 and 2 have different ministries, so no reuse test.
        # But verify ministry nodes exist
        ministry_count = stats["node_type_counts"].get("MINISTRY", 0)
        assert ministry_count >= 1

    def test_document_reuse(self):
        """Aadhaar is required by both schemes — should be one node."""
        graph, _, _ = _build_test_graph()
        aadhaar_node = make_document_id("Aadhaar Card")
        assert aadhaar_node in graph

    def test_category_extracted_from_rules(self):
        """Categories (SC/ST) should be extracted from eligibility rules."""
        graph, stats, _ = _build_test_graph()
        cat_count = stats["node_type_counts"].get("CATEGORY", 0)
        assert cat_count >= 2  # SC, ST

    def test_deterministic_build(self):
        """Building twice from same data produces same structure (§34)."""
        g1, s1, _ = _build_test_graph()
        g2, s2, _ = _build_test_graph()
        assert s1["total_nodes"] == s2["total_nodes"]
        assert s1["total_edges"] == s2["total_edges"]
        assert set(g1.nodes()) == set(g2.nodes())

    def test_no_unknown_state_node(self):
        """Unknown values should NOT create graph nodes (§81)."""
        graph, _, _ = _build_test_graph()
        assert "STATE:UNKNOWN" not in graph

    def test_no_warnings_for_clean_data(self):
        _, _, warnings = _build_test_graph()
        assert len(warnings) == 0


# ─── Serialization Tests ────────────────────────────────────

class TestSerialization:
    def test_graph_to_json_roundtrip(self):
        graph, _, _ = _build_test_graph()
        json_data = graph_to_json(graph)
        restored = json_to_graph(json_data)
        assert graph.number_of_nodes() == restored.number_of_nodes()
        assert graph.number_of_edges() == restored.number_of_edges()

    def test_node_attributes_preserved(self):
        graph, _, _ = _build_test_graph()
        json_data = graph_to_json(graph)
        restored = json_to_graph(json_data)
        scheme_node = make_scheme_id("TEST_SCHEME_001")
        assert restored.nodes[scheme_node]["name"] == "Test Agriculture Scheme"

    def test_graph_hash_deterministic(self):
        graph, _, _ = _build_test_graph()
        h1 = compute_graph_hash(graph_to_json(graph))
        h2 = compute_graph_hash(graph_to_json(graph))
        assert h1 == h2

    def test_save_and_load_snapshot(self):
        graph, stats, _ = _build_test_graph()
        with tempfile.TemporaryDirectory() as tmpdir:
            save_graph_snapshot(graph, stats, base_dir=tmpdir)
            loaded, metadata = load_graph_snapshot(base_dir=tmpdir)
            assert loaded.number_of_nodes() == graph.number_of_nodes()
            assert loaded.number_of_edges() == graph.number_of_edges()
            assert metadata["corpus_version"] == "1.0.0"


# ─── Validation Tests ────────────────────────────────────────

class TestValidation:
    def test_valid_graph_passes(self):
        graph, _, _ = _build_test_graph()
        result = validate_graph(graph)
        assert result.is_valid

    def test_corpus_consistency_pass(self):
        graph, _, _ = _build_test_graph()
        ids = [s["scheme_id"] for s in SAMPLE_SCHEMES]
        result = validate_graph(graph, corpus_scheme_ids=ids)
        assert result.is_valid

    def test_corpus_consistency_fail_missing(self):
        graph, _, _ = _build_test_graph()
        ids = [s["scheme_id"] for s in SAMPLE_SCHEMES] + ["NONEXISTENT_SCHEME"]
        result = validate_graph(graph, corpus_scheme_ids=ids)
        assert not result.is_valid

    def test_no_orphaned_rules(self):
        graph, _, _ = _build_test_graph()
        result = validate_graph(graph)
        for e in result.errors:
            assert "Orphaned rule" not in e

    def test_coverage_metrics(self):
        graph, _, _ = _build_test_graph()
        coverage = calculate_coverage_metrics(graph)
        assert "schemes_with_source" in coverage
        assert coverage["schemes_with_source"] > 0


# ─── Query Tests ─────────────────────────────────────────────

class TestQueries:
    def setup_method(self):
        graph, _, _ = _build_test_graph()
        self.repo = KnowledgeGraphRepository(graph, {"corpus_version": "1.0.0"})

    def test_get_scheme_node(self):
        node = self.repo.get_scheme_node("TEST_SCHEME_001")
        assert node is not None
        assert node["name"] == "Test Agriculture Scheme"

    def test_get_scheme_node_not_found(self):
        node = self.repo.get_scheme_node("NONEXISTENT")
        assert node is None

    def test_find_schemes_for_state_karnataka(self):
        schemes = self.repo.find_schemes_for_state("Karnataka")
        # Should include TEST_SCHEME_002 (Karnataka) + TEST_SCHEME_001 (central)
        # + TEST_SCHEME_003 (Karnataka)
        assert "TEST_SCHEME_002" in schemes
        assert "TEST_SCHEME_001" in schemes  # Central scheme

    def test_find_schemes_for_crop_ragi(self):
        schemes = self.repo.find_schemes_for_crop("ragi")
        assert "TEST_SCHEME_002" in schemes

    def test_find_schemes_for_state_and_crop(self):
        schemes = self.repo.find_schemes_for_state_and_crop("Karnataka", "ragi")
        assert "TEST_SCHEME_002" in schemes

    def test_find_schemes_for_nonexistent_state(self):
        schemes = self.repo.find_schemes_for_state("Narnia")
        # Should still include central/global schemes
        assert "TEST_SCHEME_001" in schemes

    def test_find_schemes_for_nonexistent_crop(self):
        schemes = self.repo.find_schemes_for_crop("mango")
        assert len(schemes) == 0

    def test_get_related_states(self):
        states = self.repo.get_related_states("TEST_SCHEME_002")
        assert "Karnataka" in states

    def test_get_related_crops(self):
        crops = self.repo.get_related_crops("TEST_SCHEME_002")
        assert "ragi" in crops

    def test_get_related_documents(self):
        docs = self.repo.get_related_documents("TEST_SCHEME_001")
        assert len(docs) >= 1

    def test_get_related_rules(self):
        rules = self.repo.get_related_rules("TEST_SCHEME_001")
        assert len(rules) >= 1

    def test_get_neighbors(self):
        neighbors = self.repo.get_neighbors(make_scheme_id("TEST_SCHEME_002"))
        assert len(neighbors) > 0


# ─── Profile Candidate Query Tests ──────────────────────────

class TestProfileQuery:
    def setup_method(self):
        graph, _, _ = _build_test_graph()
        self.repo = KnowledgeGraphRepository(graph, {"corpus_version": "1.0.0"})

    def test_basic_profile_query(self):
        candidates = self.repo.find_candidates_for_profile({
            "state": "Karnataka",
            "primary_crop": "ragi",
        })
        assert len(candidates) > 0
        sids = [c.scheme_id for c in candidates]
        assert "TEST_SCHEME_002" in sids

    def test_profile_returns_graph_candidates(self):
        candidates = self.repo.find_candidates_for_profile({
            "state": "Karnataka",
        })
        assert all(isinstance(c, GraphCandidate) for c in candidates)

    def test_candidate_has_match_evidence(self):
        candidates = self.repo.find_candidates_for_profile({
            "state": "Karnataka",
            "primary_crop": "ragi",
        })
        # Find the Karnataka scheme
        ka_candidates = [c for c in candidates if c.scheme_id == "TEST_SCHEME_002"]
        assert len(ka_candidates) == 1
        c = ka_candidates[0]
        assert "state" in c.matched_relations
        assert "crop" in c.matched_relations
        assert c.graph_match_score >= 2

    def test_candidate_sorted_by_score(self):
        candidates = self.repo.find_candidates_for_profile({
            "state": "Karnataka",
            "primary_crop": "ragi",
        })
        scores = [c.graph_match_score for c in candidates]
        assert scores == sorted(scores, reverse=True)

    def test_empty_profile_returns_empty(self):
        candidates = self.repo.find_candidates_for_profile({})
        assert len(candidates) == 0

    def test_category_match(self):
        candidates = self.repo.find_candidates_for_profile({
            "state": "Karnataka",
            "category": "SC",
        })
        sids = [c.scheme_id for c in candidates]
        assert "TEST_SCHEME_002" in sids

    def test_candidate_to_dict(self):
        candidates = self.repo.find_candidates_for_profile({
            "state": "Karnataka",
        })
        assert len(candidates) > 0
        d = candidates[0].to_dict()
        assert "scheme_id" in d
        assert "matched_relations" in d
        assert "graph_match_score" in d


# ─── Path Query Tests ────────────────────────────────────────

class TestPathQuery:
    def setup_method(self):
        graph, _, _ = _build_test_graph()
        self.repo = KnowledgeGraphRepository(graph, {"corpus_version": "1.0.0"})

    def test_find_path(self):
        paths = self.repo.find_paths_between(
            make_state_id("Karnataka"),
            make_scheme_id("TEST_SCHEME_002"),
            max_depth=2,
        )
        assert len(paths) > 0

    def test_no_path_for_unrelated(self):
        paths = self.repo.find_paths_between(
            make_crop_id("mango"),
            make_scheme_id("TEST_SCHEME_001"),
            max_depth=2,
        )
        assert len(paths) == 0


# ─── Graph Candidate Model Tests ────────────────────────────

class TestGraphCandidate:
    def test_to_dict(self):
        c = GraphCandidate(
            scheme_id="PM_KISAN",
            scheme_name="PM-KISAN",
            matched_relations=["state", "crop"],
            matched_nodes=["Karnataka", "Ragi"],
            graph_match_score=2,
            source_corpus_version="1.0.0",
        )
        d = c.to_dict()
        assert d["scheme_id"] == "PM_KISAN"
        assert d["graph_match_score"] == 2
        assert len(d["matched_relations"]) == 2


# ─── Version Consistency Tests ───────────────────────────────

class TestVersionConsistency:
    def test_graph_stores_corpus_version(self):
        graph, _, _ = _build_test_graph()
        assert graph.graph["corpus_version"] == "1.0.0"

    def test_metadata_in_snapshot(self):
        graph, stats, _ = _build_test_graph()
        with tempfile.TemporaryDirectory() as tmpdir:
            save_graph_snapshot(graph, stats, base_dir=tmpdir, corpus_version="1.0.0")
            _, metadata = load_graph_snapshot(base_dir=tmpdir)
            assert metadata["corpus_version"] == "1.0.0"


# ─── Failure Mode Tests ─────────────────────────────────────

class TestFailureModes:
    def test_missing_graph_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(FileNotFoundError):
                load_graph_snapshot(base_dir=tmpdir)

    def test_corrupt_graph_handled(self):
        """Corrupt JSON should raise, not crash silently."""
        with tempfile.TemporaryDirectory() as tmpdir:
            current = os.path.join(tmpdir, "current")
            os.makedirs(current)
            with open(os.path.join(current, "graph.json"), "w") as f:
                f.write("{invalid json!!!")
            with pytest.raises(Exception):
                load_graph_snapshot(base_dir=tmpdir)

    def test_empty_schemes_builds(self):
        """Building from empty corpus should work (no crash)."""
        builder = KnowledgeGraphBuilder()
        graph = builder.build_from_corpus([], corpus_version="1.0.0")
        assert graph.number_of_nodes() >= 1  # At least COUNTRY:INDIA
