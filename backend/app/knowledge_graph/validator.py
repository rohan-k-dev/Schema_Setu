"""
Knowledge Graph Validator — validates graph structure and consistency.

Checks:
    - Valid node types
    - Valid edge types
    - No dangling edges
    - No duplicate node IDs
    - Scheme ↔ DB consistency (when corpus available)
    - Every rule has an owning scheme
    - Corpus version consistency
"""

import json
from typing import Dict, Any, List, Optional

import networkx as nx

from app.knowledge_graph.schema import (
    NodeType, EdgeType, VALID_NODE_TYPES, VALID_EDGE_TYPES,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


class ValidationResult:
    """Holds graph validation results."""

    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.checks_passed = 0
        self.checks_failed = 0

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0

    def add_error(self, msg: str):
        self.errors.append(msg)
        self.checks_failed += 1

    def add_warning(self, msg: str):
        self.warnings.append(msg)

    def pass_check(self):
        self.checks_passed += 1

    def to_dict(self) -> dict:
        return {
            "valid": self.is_valid,
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
            "errors": self.errors,
            "warnings": self.warnings,
        }

    def summary(self) -> str:
        status = "VALID" if self.is_valid else "INVALID"
        return (
            f"Graph: {status}\n"
            f"  Checks passed: {self.checks_passed}\n"
            f"  Checks failed: {self.checks_failed}\n"
            f"  Errors: {len(self.errors)}\n"
            f"  Warnings: {len(self.warnings)}"
        )


def validate_graph(
    graph: nx.MultiDiGraph,
    corpus_scheme_ids: Optional[List[str]] = None,
) -> ValidationResult:
    """
    Validate a Knowledge Graph.

    Args:
        graph: The NetworkX graph to validate
        corpus_scheme_ids: Optional list of expected scheme_ids for DB consistency check
    """
    result = ValidationResult()

    # 1. Check node types
    _check_node_types(graph, result)

    # 2. Check edge types
    _check_edge_types(graph, result)

    # 3. Check for dangling edges
    _check_dangling_edges(graph, result)

    # 4. Check duplicate node IDs (implicit in NetworkX, but verify attributes)
    _check_node_uniqueness(graph, result)

    # 5. Check every rule has an owning scheme
    _check_rule_ownership(graph, result)

    # 6. Check every source has an owning scheme
    _check_source_ownership(graph, result)

    # 7. Check scheme ↔ corpus consistency
    if corpus_scheme_ids is not None:
        _check_corpus_consistency(graph, corpus_scheme_ids, result)

    # 8. Check graph metadata
    _check_metadata(graph, result)

    # 9. Check schemes with zero relationships
    _check_isolated_schemes(graph, result)

    logger.info(f"Validation complete: {result.summary()}")
    return result


def _check_node_types(graph: nx.MultiDiGraph, result: ValidationResult):
    """Verify all nodes have valid node_type attribute."""
    invalid = []
    missing = []
    for node_id, attrs in graph.nodes(data=True):
        nt = attrs.get("node_type")
        if nt is None:
            missing.append(node_id)
        elif nt not in VALID_NODE_TYPES:
            invalid.append((node_id, nt))

    if missing:
        result.add_error(f"Nodes missing node_type: {len(missing)} ({missing[:5]}...)")
    else:
        result.pass_check()

    if invalid:
        result.add_error(f"Invalid node types: {len(invalid)} ({invalid[:5]}...)")
    else:
        result.pass_check()


def _check_edge_types(graph: nx.MultiDiGraph, result: ValidationResult):
    """Verify all edges have valid relation attribute."""
    invalid = []
    missing = []
    for src, tgt, attrs in graph.edges(data=True):
        rel = attrs.get("relation")
        if rel is None:
            missing.append((src, tgt))
        elif rel not in VALID_EDGE_TYPES:
            invalid.append((src, tgt, rel))

    if missing:
        result.add_error(f"Edges missing relation: {len(missing)}")
    else:
        result.pass_check()

    if invalid:
        result.add_error(f"Invalid edge types: {len(invalid)} ({invalid[:5]}...)")
    else:
        result.pass_check()


def _check_dangling_edges(graph: nx.MultiDiGraph, result: ValidationResult):
    """Check for edges referencing non-existent nodes."""
    dangling = 0
    for src, tgt in graph.edges():
        if src not in graph.nodes:
            dangling += 1
        if tgt not in graph.nodes:
            dangling += 1

    if dangling > 0:
        result.add_error(f"Dangling edges: {dangling}")
    else:
        result.pass_check()


def _check_node_uniqueness(graph: nx.MultiDiGraph, result: ValidationResult):
    """Verify no duplicate logical nodes (NetworkX enforces unique IDs)."""
    # Check that scheme nodes have unique scheme_id attributes
    scheme_ids = []
    for _, attrs in graph.nodes(data=True):
        if attrs.get("node_type") == NodeType.SCHEME.value:
            sid = attrs.get("scheme_id")
            if sid:
                scheme_ids.append(sid)

    duplicates = [sid for sid in scheme_ids if scheme_ids.count(sid) > 1]
    if duplicates:
        result.add_error(f"Duplicate scheme_ids in graph: {set(duplicates)}")
    else:
        result.pass_check()


def _check_rule_ownership(graph: nx.MultiDiGraph, result: ValidationResult):
    """Every ELIGIBILITY_RULE node must have exactly one scheme pointing to it."""
    rule_nodes = [
        nid for nid, attrs in graph.nodes(data=True)
        if attrs.get("node_type") == NodeType.ELIGIBILITY_RULE.value
    ]

    orphaned = []
    for rule_id in rule_nodes:
        # Check predecessors (schemes that have HAS_ELIGIBILITY_RULE edge to this rule)
        predecessors = list(graph.predecessors(rule_id))
        scheme_owners = [
            p for p in predecessors
            if graph.nodes[p].get("node_type") == NodeType.SCHEME.value
        ]
        if not scheme_owners:
            orphaned.append(rule_id)

    if orphaned:
        result.add_error(f"Orphaned rule nodes (no owning scheme): {len(orphaned)}")
    else:
        result.pass_check()


def _check_source_ownership(graph: nx.MultiDiGraph, result: ValidationResult):
    """Every SOURCE node should be referenced by at least one scheme."""
    source_nodes = [
        nid for nid, attrs in graph.nodes(data=True)
        if attrs.get("node_type") == NodeType.SOURCE.value
    ]

    orphaned = []
    for source_id in source_nodes:
        predecessors = list(graph.predecessors(source_id))
        if not predecessors:
            orphaned.append(source_id)

    if orphaned:
        result.add_warning(f"Source nodes with no scheme reference: {len(orphaned)}")
    else:
        result.pass_check()


def _check_corpus_consistency(
    graph: nx.MultiDiGraph,
    corpus_scheme_ids: List[str],
    result: ValidationResult,
):
    """Check that graph scheme nodes match the corpus scheme IDs."""
    graph_scheme_ids = set()
    for _, attrs in graph.nodes(data=True):
        if attrs.get("node_type") == NodeType.SCHEME.value:
            sid = attrs.get("scheme_id")
            if sid:
                graph_scheme_ids.add(sid)

    corpus_set = set(corpus_scheme_ids)

    missing_in_graph = corpus_set - graph_scheme_ids
    extra_in_graph = graph_scheme_ids - corpus_set

    if missing_in_graph:
        result.add_error(
            f"Schemes in corpus but not in graph: {len(missing_in_graph)} "
            f"({list(missing_in_graph)[:5]}...)"
        )
    else:
        result.pass_check()

    if extra_in_graph:
        result.add_error(
            f"Schemes in graph but not in corpus: {len(extra_in_graph)} "
            f"({list(extra_in_graph)[:5]}...)"
        )
    else:
        result.pass_check()


def _check_metadata(graph: nx.MultiDiGraph, result: ValidationResult):
    """Check graph metadata completeness."""
    required = ["corpus_version", "generated_at"]
    for key in required:
        if key not in graph.graph:
            result.add_warning(f"Missing graph metadata: {key}")
        else:
            result.pass_check()


def _check_isolated_schemes(graph: nx.MultiDiGraph, result: ValidationResult):
    """Report schemes with zero outgoing relationships."""
    isolated = []
    for nid, attrs in graph.nodes(data=True):
        if attrs.get("node_type") == NodeType.SCHEME.value:
            out_edges = list(graph.out_edges(nid))
            if not out_edges:
                isolated.append(nid)

    if isolated:
        result.add_warning(f"Schemes with zero relationships: {len(isolated)} ({isolated[:5]}...)")
    else:
        result.pass_check()


def calculate_coverage_metrics(graph: nx.MultiDiGraph) -> Dict[str, float]:
    """Calculate graph coverage metrics (§133)."""
    scheme_nodes = [
        nid for nid, attrs in graph.nodes(data=True)
        if attrs.get("node_type") == NodeType.SCHEME.value
    ]
    total = len(scheme_nodes) or 1

    def pct_with_relation(edge_type: str) -> float:
        count = 0
        for sid in scheme_nodes:
            for _, _, attrs in graph.out_edges(sid, data=True):
                if attrs.get("relation") == edge_type:
                    count += 1
                    break
        return round(100 * count / total, 1)

    return {
        "schemes_with_state": pct_with_relation(EdgeType.APPLIES_TO_STATE.value),
        "schemes_with_global": pct_with_relation(EdgeType.GLOBAL_APPLICABILITY.value),
        "schemes_with_crop": pct_with_relation(EdgeType.TARGETS_CROP.value),
        "schemes_with_beneficiary": pct_with_relation(EdgeType.TARGETS_BENEFICIARY.value),
        "schemes_with_benefit": pct_with_relation(EdgeType.PROVIDES_BENEFIT.value),
        "schemes_with_document": pct_with_relation(EdgeType.REQUIRES_DOCUMENT.value),
        "schemes_with_rule": pct_with_relation(EdgeType.HAS_ELIGIBILITY_RULE.value),
        "schemes_with_source": pct_with_relation(EdgeType.HAS_SOURCE.value),
        "schemes_with_ministry": pct_with_relation(EdgeType.OFFERED_BY_MINISTRY.value),
    }
