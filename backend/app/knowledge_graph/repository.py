"""
Knowledge Graph Repository — typed query interface over the graph.

Hides NetworkX implementation behind clean domain methods.
All queries are read-only. No graph mutation.
No eval/exec. User input is normalized before lookup.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Set

import networkx as nx

from app.knowledge_graph.schema import (
    NodeType, EdgeType,
    make_state_id, make_crop_id, make_beneficiary_id,
    make_category_id, make_occupation_id, make_gender_id,
    make_district_id, make_country_id,
    should_skip_value, _normalize_for_id,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class GraphCandidate:
    """A scheme candidate discovered through graph traversal (§55)."""
    scheme_id: str
    scheme_name: str
    matched_relations: List[str] = field(default_factory=list)
    matched_nodes: List[str] = field(default_factory=list)
    graph_match_score: int = 0
    source_corpus_version: str = ""

    def to_dict(self) -> dict:
        return {
            "scheme_id": self.scheme_id,
            "scheme_name": self.scheme_name,
            "matched_relations": self.matched_relations,
            "matched_nodes": self.matched_nodes,
            "graph_match_score": self.graph_match_score,
            "source_corpus_version": self.source_corpus_version,
        }


class KnowledgeGraphRepository:
    """
    Read-only query interface over the Knowledge Graph.

    Responsibilities:
        - Load graph
        - Access nodes and neighbors
        - Query relationships
        - Return typed GraphCandidate results
        - Map user profile to graph entities
        - Find candidate schemes via traversal

    Does NOT:
        - Call Groq/Tavily/Sarvam
        - Evaluate eligibility
        - Mutate the graph
    """

    def __init__(self, graph: nx.MultiDiGraph, metadata: Optional[dict] = None):
        self._graph = graph
        self._metadata = metadata or {}

    @property
    def graph(self) -> nx.MultiDiGraph:
        return self._graph

    @property
    def corpus_version(self) -> str:
        return self._metadata.get("corpus_version", self._graph.graph.get("corpus_version", ""))

    @property
    def graph_version(self) -> str:
        return self._metadata.get("graph_version", "")

    @property
    def node_count(self) -> int:
        return self._graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self._graph.number_of_edges()

    # ─── Node access ─────────────────────────────────────────

    def get_node(self, node_id: str) -> Optional[dict]:
        """Get a node's attributes by ID."""
        if node_id in self._graph:
            return dict(self._graph.nodes[node_id])
        return None

    def get_scheme_node(self, scheme_id: str) -> Optional[dict]:
        """Get a scheme node by its canonical scheme_id."""
        node_id = f"{NodeType.SCHEME.value}:{scheme_id}"
        return self.get_node(node_id)

    def get_nodes_by_type(self, node_type: NodeType) -> List[str]:
        """Get all node IDs of a given type."""
        return [
            nid for nid, attrs in self._graph.nodes(data=True)
            if attrs.get("node_type") == node_type.value
        ]

    # ─── Neighbor queries ────────────────────────────────────

    def get_neighbors(
        self,
        node_id: str,
        relationship_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get neighbors of a node, optionally filtered by relationship type.

        Returns list of {node_id, relation, attributes}.
        """
        if node_id not in self._graph:
            return []

        results = []
        for _, tgt, attrs in self._graph.out_edges(node_id, data=True):
            rel = attrs.get("relation", "")
            if relationship_type and rel != relationship_type:
                continue
            results.append({
                "node_id": tgt,
                "relation": rel,
                "attributes": dict(self._graph.nodes[tgt]),
            })
        return results

    def get_related_states(self, scheme_id: str) -> List[str]:
        """Get states a scheme applies to."""
        node_id = f"{NodeType.SCHEME.value}:{scheme_id}"
        neighbors = self.get_neighbors(node_id, EdgeType.APPLIES_TO_STATE.value)
        return [n["attributes"].get("canonical_name", "") for n in neighbors]

    def get_related_crops(self, scheme_id: str) -> List[str]:
        node_id = f"{NodeType.SCHEME.value}:{scheme_id}"
        neighbors = self.get_neighbors(node_id, EdgeType.TARGETS_CROP.value)
        return [n["attributes"].get("canonical_name", "") for n in neighbors]

    def get_related_documents(self, scheme_id: str) -> List[str]:
        node_id = f"{NodeType.SCHEME.value}:{scheme_id}"
        neighbors = self.get_neighbors(node_id, EdgeType.REQUIRES_DOCUMENT.value)
        return [n["attributes"].get("canonical_name", "") for n in neighbors]

    def get_related_rules(self, scheme_id: str) -> List[dict]:
        node_id = f"{NodeType.SCHEME.value}:{scheme_id}"
        neighbors = self.get_neighbors(node_id, EdgeType.HAS_ELIGIBILITY_RULE.value)
        return [n["attributes"] for n in neighbors]

    def get_related_sources(self, scheme_id: str) -> List[dict]:
        node_id = f"{NodeType.SCHEME.value}:{scheme_id}"
        neighbors = self.get_neighbors(node_id, EdgeType.HAS_SOURCE.value)
        return [n["attributes"] for n in neighbors]

    # ─── Scheme discovery queries ────────────────────────────

    def find_schemes_for_state(self, state: str) -> Set[str]:
        """Find schemes connected to a state + central/global schemes (§51)."""
        state_id = make_state_id(state)
        candidates = set()

        # State-specific schemes
        if state_id in self._graph:
            for pred in self._graph.predecessors(state_id):
                attrs = self._graph.nodes[pred]
                if attrs.get("node_type") == NodeType.SCHEME.value:
                    candidates.add(attrs.get("scheme_id", ""))

        # Global/central schemes (connected to COUNTRY:INDIA)
        country_id = make_country_id("INDIA")
        if country_id in self._graph:
            for pred in self._graph.predecessors(country_id):
                attrs = self._graph.nodes.get(pred, {})
                if attrs.get("node_type") == NodeType.SCHEME.value:
                    # Only include if connected via GLOBAL_APPLICABILITY
                    for _, _, eattrs in self._graph.out_edges(pred, data=True):
                        if eattrs.get("relation") == EdgeType.GLOBAL_APPLICABILITY.value:
                            candidates.add(attrs.get("scheme_id", ""))
                            break

        candidates.discard("")
        return candidates

    def find_schemes_for_crop(self, crop: str) -> Set[str]:
        """Find schemes connected to a crop (§52)."""
        crop_id = make_crop_id(crop)
        candidates = set()

        if crop_id in self._graph:
            for pred in self._graph.predecessors(crop_id):
                attrs = self._graph.nodes[pred]
                if attrs.get("node_type") == NodeType.SCHEME.value:
                    candidates.add(attrs.get("scheme_id", ""))

        candidates.discard("")
        return candidates

    def find_schemes_for_state_and_crop(self, state: str, crop: str) -> Set[str]:
        """Find schemes connected to both state AND crop (§50)."""
        state_schemes = self.find_schemes_for_state(state)
        crop_schemes = self.find_schemes_for_crop(crop)

        # Schemes connected to crop but with NO state restriction (global)
        global_crop_schemes = set()
        for sid in crop_schemes:
            node_id = f"{NodeType.SCHEME.value}:{sid}"
            has_state = False
            for _, _, attrs in self._graph.out_edges(node_id, data=True):
                if attrs.get("relation") == EdgeType.APPLIES_TO_STATE.value:
                    has_state = True
                    break
            if not has_state:
                global_crop_schemes.add(sid)

        # State schemes ∩ crop schemes + global crop schemes
        return (state_schemes & crop_schemes) | (state_schemes & global_crop_schemes) | global_crop_schemes

    def find_schemes_for_beneficiary(self, beneficiary: str) -> Set[str]:
        benef_id = make_beneficiary_id(beneficiary)
        candidates = set()
        if benef_id in self._graph:
            for pred in self._graph.predecessors(benef_id):
                attrs = self._graph.nodes[pred]
                if attrs.get("node_type") == NodeType.SCHEME.value:
                    candidates.add(attrs.get("scheme_id", ""))
        candidates.discard("")
        return candidates

    def find_schemes_for_category(self, category: str) -> Set[str]:
        cat_id = make_category_id(category)
        candidates = set()
        if cat_id in self._graph:
            for pred in self._graph.predecessors(cat_id):
                attrs = self._graph.nodes[pred]
                if attrs.get("node_type") == NodeType.SCHEME.value:
                    candidates.add(attrs.get("scheme_id", ""))
        candidates.discard("")
        return candidates

    def _edge_targets(self, scheme_id: str, relation: str) -> Set[str]:
        """Node IDs a scheme points to via `relation`."""
        node_id = f"{NodeType.SCHEME.value}:{scheme_id}"
        if node_id not in self._graph:
            return set()
        return {v for _, v, a in self._graph.out_edges(node_id, data=True) if a.get("relation") == relation}

    # ─── Profile candidate query (§53) ───────────────────────

    def find_candidates_for_profile(self, profile: dict) -> List[GraphCandidate]:
        """
        Find candidate schemes based on a user profile (§53).

        Maps categorical profile fields to graph nodes, traverses,
        and returns candidates with match evidence.

        Does NOT evaluate eligibility or produce final scores.
        """
        corpus_version = self.corpus_version

        # Collect candidates per dimension
        dimension_matches: Dict[str, Set[str]] = {}

        # State
        state = profile.get("state")
        if state and not should_skip_value(state):
            dimension_matches["state"] = self.find_schemes_for_state(state)

        # Crop
        crop = profile.get("primary_crop") or profile.get("crop")
        if crop and not should_skip_value(crop):
            dimension_matches["crop"] = self.find_schemes_for_crop(crop)

        # Category
        category = profile.get("category") or profile.get("caste_category")
        if category and not should_skip_value(category):
            dimension_matches["category"] = self.find_schemes_for_category(category)

        # Gender
        gender = profile.get("gender")
        if gender and not should_skip_value(gender):
            gender_id = make_gender_id(gender)
            gender_schemes = set()
            if gender_id in self._graph:
                for pred in self._graph.predecessors(gender_id):
                    attrs = self._graph.nodes[pred]
                    if attrs.get("node_type") == NodeType.SCHEME.value:
                        gender_schemes.add(attrs.get("scheme_id", ""))
            gender_schemes.discard("")
            if gender_schemes:
                dimension_matches["gender"] = gender_schemes

        # Occupation
        occupation = profile.get("occupation")
        if occupation and not should_skip_value(occupation):
            occ_id = make_occupation_id(occupation)
            occ_schemes = set()
            if occ_id in self._graph:
                for pred in self._graph.predecessors(occ_id):
                    attrs = self._graph.nodes[pred]
                    if attrs.get("node_type") == NodeType.SCHEME.value:
                        occ_schemes.add(attrs.get("scheme_id", ""))
            occ_schemes.discard("")
            if occ_schemes:
                dimension_matches["occupation"] = occ_schemes

        # Beneficiary (if profile has it)
        beneficiary = profile.get("beneficiary_type")
        if beneficiary and not should_skip_value(beneficiary):
            dimension_matches["beneficiary"] = self.find_schemes_for_beneficiary(beneficiary)

        if not dimension_matches:
            return []

        # Collect ALL candidate scheme_ids across all dimensions
        all_candidates: Set[str] = set()
        for schemes in dimension_matches.values():
            all_candidates |= schemes

        # Respect restrictions (Phase 7 BUG-007): a scheme restricted to other
        # states, or to other crops, is not a candidate for this profile — the
        # union above used to admit e.g. oilseed schemes for a ragi farmer.
        state_id = make_state_id(state) if state and not should_skip_value(state) else None
        crop_id = make_crop_id(crop) if crop and not should_skip_value(crop) else None
        targeting: Dict[str, int] = {}
        for sid in list(all_candidates):
            state_targets = self._edge_targets(sid, EdgeType.APPLIES_TO_STATE.value)
            crop_targets = self._edge_targets(sid, EdgeType.TARGETS_CROP.value)
            if state_id and state_targets and state_id not in state_targets:
                all_candidates.discard(sid)
                continue
            if crop_id and crop_targets and crop_id not in crop_targets:
                all_candidates.discard(sid)
                continue
            targeting[sid] = int(bool(state_id and state_id in state_targets)) +                 int(bool(crop_id and crop_id in crop_targets))

        # Build GraphCandidate for each with match evidence
        results = []
        for sid in sorted(all_candidates):
            matched_relations = []
            matched_nodes = []

            for dim_name, dim_schemes in dimension_matches.items():
                if sid in dim_schemes:
                    matched_relations.append(dim_name)
                    matched_nodes.append(profile.get(
                        dim_name,
                        profile.get(f"primary_{dim_name}", dim_name),
                    ))

            scheme_node = self.get_scheme_node(sid)
            scheme_name = scheme_node.get("name", "") if scheme_node else ""

            candidate = GraphCandidate(
                scheme_id=sid,
                scheme_name=scheme_name,
                matched_relations=matched_relations,
                matched_nodes=matched_nodes,
                # Specifically targeted matches (state/crop restriction the user meets)
                # count double, so they rank above nationally applicable schemes.
                graph_match_score=len(matched_relations) + targeting.get(sid, 0),
                source_corpus_version=corpus_version,
            )
            results.append(candidate)

        # Sort by score descending, then by scheme_id
        results.sort(key=lambda c: (-c.graph_match_score, c.scheme_id))

        return results

    # ─── Path queries (§93) ──────────────────────────────────

    def find_paths_between(
        self,
        source_id: str,
        target_id: str,
        max_depth: int = 3,
    ) -> List[List[str]]:
        """
        Find short relationship paths between two nodes.

        Uses breadth-first search with depth limit for safety (§93).
        Returns list of paths (each path is a list of node IDs).
        """
        if source_id not in self._graph or target_id not in self._graph:
            return []

        try:
            undirected = self._graph.to_undirected()
            paths = list(nx.all_simple_paths(
                undirected, source_id, target_id, cutoff=max_depth
            ))
            return paths[:10]  # Limit results
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

    # ─── Health check ────────────────────────────────────────

    def health_check(self) -> dict:
        """Quick health check of the loaded graph."""
        return {
            "loaded": True,
            "nodes": self.node_count,
            "edges": self.edge_count,
            "corpus_version": self.corpus_version,
            "graph_version": self.graph_version,
        }
