"""
Knowledge Graph Builder — constructs a NetworkX MultiDiGraph from corpus data.

Reads data from validated corpus JSON (or PostgreSQL via repositories when
available) and creates a deterministic, reproducible graph.

Architecture:
    Validated Corpus / PostgreSQL
        ↓
    Graph Builder
        ↓
    NetworkX MultiDiGraph
        ↓
    Graph Snapshot (JSON)

Key properties:
    - Deterministic: same data → same graph
    - Reproducible: sort all records before processing
    - Source-backed: all relationships derived from canonical data
    - No LLM dependency
    - No network dependency
"""

import json
import os
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

import networkx as nx

from app.knowledge_graph.schema import (
    NodeType, EdgeType,
    make_scheme_id, make_state_id, make_district_id,
    make_crop_id, make_beneficiary_id, make_category_id,
    make_occupation_id, make_gender_id, make_ministry_id,
    make_department_id, make_benefit_id, make_document_id,
    make_rule_id, make_source_id, make_country_id,
    should_skip_value, _normalize_for_id,
)
from app.core.logging import get_logger

logger = get_logger(__name__)

# Builder version for metadata tracking
BUILDER_VERSION = "1.0.0"


class KnowledgeGraphBuilder:
    """
    Builds a NetworkX MultiDiGraph from validated scheme corpus data.

    Usage:
        builder = KnowledgeGraphBuilder()
        graph = builder.build_from_corpus(schemes_list, corpus_version="1.0.0")
    """

    def __init__(self):
        self.graph: nx.MultiDiGraph = nx.MultiDiGraph()
        self.stats: Dict[str, int] = {}
        self._warnings: List[str] = []

    def build_from_corpus(
        self,
        schemes: List[Dict[str, Any]],
        corpus_version: str = "1.0.0",
        schema_version: str = "1.0.0",
    ) -> nx.MultiDiGraph:
        """
        Build the complete Knowledge Graph from a list of scheme dicts.

        Args:
            schemes: List of validated scheme dicts (Phase 1 format)
            corpus_version: Version of the source corpus
            schema_version: Version of the graph schema

        Returns:
            NetworkX MultiDiGraph with all nodes and edges
        """
        self.graph = nx.MultiDiGraph()
        self._warnings = []

        # Store graph metadata
        self.graph.graph["corpus_version"] = corpus_version
        self.graph.graph["schema_version"] = schema_version
        self.graph.graph["builder_version"] = BUILDER_VERSION
        self.graph.graph["generated_at"] = datetime.now(timezone.utc).isoformat()

        # 1. Create root COUNTRY:INDIA node
        self._add_country_node()

        # 2. Sort schemes deterministically
        sorted_schemes = sorted(schemes, key=lambda s: s.get("scheme_id", ""))

        # 3. Process each scheme
        for scheme_data in sorted_schemes:
            try:
                self._process_scheme(scheme_data, corpus_version)
            except Exception as e:
                sid = scheme_data.get("scheme_id", "?")
                self._warnings.append(f"Error processing scheme {sid}: {e}")
                logger.warning(f"Error processing scheme {sid}: {e}")

        # 4. Calculate statistics
        self.stats = self._calculate_stats()
        self.graph.graph["node_count"] = self.stats["total_nodes"]
        self.graph.graph["edge_count"] = self.stats["total_edges"]

        logger.info(
            f"Graph built: {self.stats['total_nodes']} nodes, "
            f"{self.stats['total_edges']} edges, "
            f"{len(self._warnings)} warnings"
        )

        return self.graph

    def get_warnings(self) -> List[str]:
        return list(self._warnings)

    def get_stats(self) -> Dict[str, Any]:
        return dict(self.stats)

    # ─── Node creators ───────────────────────────────────────

    def _add_country_node(self):
        node_id = make_country_id("INDIA")
        self.graph.add_node(
            node_id,
            node_type=NodeType.COUNTRY.value,
            canonical_name="India",
        )

    def _add_scheme_node(self, data: dict, corpus_version: str) -> str:
        scheme_id = data["scheme_id"]
        node_id = make_scheme_id(scheme_id)

        level = data.get("level")
        if isinstance(level, dict):
            level = level.get("value")
        status = data.get("status", "ACTIVE")
        if isinstance(status, dict):
            status = status.get("value", "ACTIVE")

        self.graph.add_node(
            node_id,
            node_type=NodeType.SCHEME.value,
            scheme_id=scheme_id,
            name=data.get("name", ""),
            status=status,
            level=level,
            ministry=data.get("ministry", ""),
            department=data.get("department", ""),
            corpus_version=corpus_version,
            last_verified_at=data.get("last_verified_at"),
        )
        return node_id

    def _add_state_node(self, state: str) -> str:
        node_id = make_state_id(state)
        if node_id not in self.graph:
            self.graph.add_node(
                node_id,
                node_type=NodeType.STATE.value,
                canonical_name=state,
                normalized_name=_normalize_for_id(state),
            )
            # Connect to India
            self.graph.add_edge(
                node_id, make_country_id("INDIA"),
                relation=EdgeType.PART_OF.value,
            )
        return node_id

    def _add_district_node(self, state: str, district: str) -> str:
        node_id = make_district_id(state, district)
        if node_id not in self.graph:
            self.graph.add_node(
                node_id,
                node_type=NodeType.DISTRICT.value,
                name=district,
                state=state,
            )
            # Connect to state
            state_id = self._add_state_node(state)
            self.graph.add_edge(
                node_id, state_id,
                relation=EdgeType.DISTRICT_OF.value,
            )
        return node_id

    def _add_crop_node(self, crop: str) -> str:
        node_id = make_crop_id(crop)
        if node_id not in self.graph:
            self.graph.add_node(
                node_id,
                node_type=NodeType.CROP.value,
                canonical_name=crop,
                normalized_name=_normalize_for_id(crop),
            )
        return node_id

    def _add_beneficiary_node(self, beneficiary: str) -> str:
        node_id = make_beneficiary_id(beneficiary)
        if node_id not in self.graph:
            self.graph.add_node(
                node_id,
                node_type=NodeType.BENEFICIARY.value,
                canonical_name=beneficiary,
                normalized_name=_normalize_for_id(beneficiary),
            )
        return node_id

    def _add_category_node(self, category: str) -> str:
        node_id = make_category_id(category)
        if node_id not in self.graph:
            self.graph.add_node(
                node_id,
                node_type=NodeType.CATEGORY.value,
                canonical_name=category,
            )
        return node_id

    def _add_occupation_node(self, occupation: str) -> str:
        node_id = make_occupation_id(occupation)
        if node_id not in self.graph:
            self.graph.add_node(
                node_id,
                node_type=NodeType.OCCUPATION.value,
                canonical_name=occupation,
            )
        return node_id

    def _add_gender_node(self, gender: str) -> str:
        node_id = make_gender_id(gender)
        if node_id not in self.graph:
            self.graph.add_node(
                node_id,
                node_type=NodeType.GENDER.value,
                canonical_name=gender,
            )
        return node_id

    def _add_ministry_node(self, ministry: str) -> str:
        node_id = make_ministry_id(ministry)
        if node_id not in self.graph:
            self.graph.add_node(
                node_id,
                node_type=NodeType.MINISTRY.value,
                canonical_name=ministry,
                normalized_name=_normalize_for_id(ministry),
            )
        return node_id

    def _add_department_node(self, department: str) -> str:
        node_id = make_department_id(department)
        if node_id not in self.graph:
            self.graph.add_node(
                node_id,
                node_type=NodeType.DEPARTMENT.value,
                canonical_name=department,
            )
        return node_id

    def _add_benefit_node(self, benefit_type: str) -> str:
        node_id = make_benefit_id(benefit_type)
        if node_id not in self.graph:
            self.graph.add_node(
                node_id,
                node_type=NodeType.BENEFIT.value,
                canonical_name=benefit_type,
            )
        return node_id

    def _add_document_node(self, doc_name: str) -> str:
        node_id = make_document_id(doc_name)
        if node_id not in self.graph:
            self.graph.add_node(
                node_id,
                node_type=NodeType.DOCUMENT.value,
                canonical_name=doc_name,
                normalized_name=_normalize_for_id(doc_name),
            )
        return node_id

    def _add_rule_node(self, scheme_id: str, rule: dict, index: int) -> str:
        rule_id_val = rule.get("rule_id")
        node_id = make_rule_id(scheme_id, index, rule_id_val)

        operator = rule.get("operator", "UNKNOWN")
        if isinstance(operator, dict):
            operator = operator.get("value", "UNKNOWN")
        logical = rule.get("logical_group", "AND")
        if isinstance(logical, dict):
            logical = logical.get("value", "AND")

        self.graph.add_node(
            node_id,
            node_type=NodeType.ELIGIBILITY_RULE.value,
            field_name=rule.get("field", ""),
            operator=operator,
            value=json.dumps(rule.get("value")),
            required=rule.get("required", True),
            logical_group=logical,
            source_text=rule.get("source_text", ""),
        )
        return node_id

    def _add_source_node(self, source: dict) -> str:
        sid = source.get("source_id", "unknown")
        node_id = make_source_id(sid)
        if node_id not in self.graph:
            stype = source.get("source_type", "UNKNOWN")
            if isinstance(stype, dict):
                stype = stype.get("value", "UNKNOWN")
            self.graph.add_node(
                node_id,
                node_type=NodeType.SOURCE.value,
                source_type=stype,
                source_name=source.get("source_name", ""),
                url=source.get("url", ""),
                verified_at=source.get("last_verified_at"),
            )
        return node_id

    # ─── Scheme processor ────────────────────────────────────

    def _process_scheme(self, data: dict, corpus_version: str):
        """Process a single scheme — create nodes and edges."""
        scheme_id = data["scheme_id"]
        scheme_node = self._add_scheme_node(data, corpus_version)

        # Level/global applicability
        level = data.get("level")
        if isinstance(level, dict):
            level = level.get("value")

        # States
        states = data.get("applicable_states")
        if states is None:
            # Central/global scheme — connect to COUNTRY:INDIA
            self.graph.add_edge(
                scheme_node, make_country_id("INDIA"),
                relation=EdgeType.GLOBAL_APPLICABILITY.value,
                corpus_version=corpus_version,
            )
        else:
            for state in sorted(states):
                if not should_skip_value(state):
                    state_node = self._add_state_node(state)
                    self.graph.add_edge(
                        scheme_node, state_node,
                        relation=EdgeType.APPLIES_TO_STATE.value,
                        corpus_version=corpus_version,
                    )

        # Districts
        districts = data.get("applicable_districts")
        if districts:
            for district in sorted(districts, key=lambda d: str(d)):
                if isinstance(district, dict):
                    state_name = district.get("state", "")
                    dist_name = district.get("district", "")
                else:
                    state_name = ""
                    dist_name = str(district)
                if dist_name and not should_skip_value(dist_name):
                    dist_node = self._add_district_node(state_name, dist_name)
                    self.graph.add_edge(
                        scheme_node, dist_node,
                        relation=EdgeType.APPLIES_TO_DISTRICT.value,
                        corpus_version=corpus_version,
                    )

        # Crops
        crops = data.get("applicable_crops")
        if crops:
            for crop in sorted(crops):
                if not should_skip_value(crop):
                    crop_node = self._add_crop_node(crop)
                    self.graph.add_edge(
                        scheme_node, crop_node,
                        relation=EdgeType.TARGETS_CROP.value,
                        corpus_version=corpus_version,
                    )

        # Beneficiaries
        for benef in sorted(data.get("target_beneficiaries", [])):
            if not should_skip_value(benef):
                benef_node = self._add_beneficiary_node(benef)
                self.graph.add_edge(
                    scheme_node, benef_node,
                    relation=EdgeType.TARGETS_BENEFICIARY.value,
                    corpus_version=corpus_version,
                )

        # Ministry
        ministry = data.get("ministry")
        if ministry and not should_skip_value(ministry):
            min_node = self._add_ministry_node(ministry)
            self.graph.add_edge(
                scheme_node, min_node,
                relation=EdgeType.OFFERED_BY_MINISTRY.value,
                corpus_version=corpus_version,
            )

        # Department
        department = data.get("department")
        if department and not should_skip_value(department):
            dept_node = self._add_department_node(department)
            self.graph.add_edge(
                scheme_node, dept_node,
                relation=EdgeType.BELONGS_TO_DEPARTMENT.value,
                corpus_version=corpus_version,
            )

        # Benefits
        for i, benefit in enumerate(sorted(
            data.get("benefits", []),
            key=lambda b: b.get("type", "") if isinstance(b.get("type"), str) else str(b.get("type", "")),
        )):
            btype = benefit.get("type", "unknown")
            if isinstance(btype, dict):
                btype = btype.get("value", "unknown")
            if not should_skip_value(btype):
                benefit_node = self._add_benefit_node(btype)
                self.graph.add_edge(
                    scheme_node, benefit_node,
                    relation=EdgeType.PROVIDES_BENEFIT.value,
                    corpus_version=corpus_version,
                    source_text=benefit.get("source_text", ""),
                )

        # Documents
        for doc in sorted(data.get("required_documents", []), key=lambda d: d.get("name", "")):
            doc_name = doc.get("name", "")
            if doc_name and not should_skip_value(doc_name):
                doc_node = self._add_document_node(doc_name)
                self.graph.add_edge(
                    scheme_node, doc_node,
                    relation=EdgeType.REQUIRES_DOCUMENT.value,
                    mandatory=doc.get("mandatory", True),
                    corpus_version=corpus_version,
                )

        # Eligibility Rules
        rules = data.get("eligibility_rules", [])
        for i, rule in enumerate(sorted(rules, key=lambda r: r.get("field", ""))):
            rule_node = self._add_rule_node(scheme_id, rule, i)
            self.graph.add_edge(
                scheme_node, rule_node,
                relation=EdgeType.HAS_ELIGIBILITY_RULE.value,
                corpus_version=corpus_version,
            )
            # Extract category/occupation/gender from rules
            self._extract_categorical_from_rule(scheme_node, rule, corpus_version)

        # Sources
        for source in sorted(data.get("source_records", []), key=lambda s: s.get("source_id", "")):
            source_node = self._add_source_node(source)
            self.graph.add_edge(
                scheme_node, source_node,
                relation=EdgeType.HAS_SOURCE.value,
                corpus_version=corpus_version,
            )

    def _extract_categorical_from_rule(self, scheme_node: str, rule: dict, cv: str):
        """Extract category/occupation/gender relationships from eligibility rules."""
        field = rule.get("field", "").lower()
        value = rule.get("value")

        if field in ("category", "caste_category", "social_category"):
            values = value if isinstance(value, list) else [value]
            for v in values:
                if v and not should_skip_value(str(v)):
                    cat_node = self._add_category_node(str(v))
                    self.graph.add_edge(
                        scheme_node, cat_node,
                        relation=EdgeType.TARGETS_CATEGORY.value,
                        corpus_version=cv,
                    )
        elif field in ("occupation", "occupation_type"):
            values = value if isinstance(value, list) else [value]
            for v in values:
                if v and not should_skip_value(str(v)):
                    occ_node = self._add_occupation_node(str(v))
                    self.graph.add_edge(
                        scheme_node, occ_node,
                        relation=EdgeType.TARGETS_OCCUPATION.value,
                        corpus_version=cv,
                    )
        elif field in ("gender", "applicant_gender"):
            values = value if isinstance(value, list) else [value]
            for v in values:
                if v and not should_skip_value(str(v)):
                    gen_node = self._add_gender_node(str(v))
                    self.graph.add_edge(
                        scheme_node, gen_node,
                        relation=EdgeType.TARGETS_GENDER.value,
                        corpus_version=cv,
                    )

    # ─── Statistics ──────────────────────────────────────────

    def _calculate_stats(self) -> Dict[str, Any]:
        """Calculate graph statistics."""
        node_type_counts = {}
        for _, attrs in self.graph.nodes(data=True):
            nt = attrs.get("node_type", "UNKNOWN")
            node_type_counts[nt] = node_type_counts.get(nt, 0) + 1

        edge_type_counts = {}
        for _, _, attrs in self.graph.edges(data=True):
            et = attrs.get("relation", "UNKNOWN")
            edge_type_counts[et] = edge_type_counts.get(et, 0) + 1

        # Connected components (treat as undirected for this)
        undirected = self.graph.to_undirected()
        components = nx.number_connected_components(undirected)

        return {
            "total_nodes": self.graph.number_of_nodes(),
            "total_edges": self.graph.number_of_edges(),
            "node_type_counts": node_type_counts,
            "edge_type_counts": edge_type_counts,
            "connected_components": components,
            "warnings": len(self._warnings),
        }


def build_graph_from_corpus_file(
    corpus_path: str,
    manifest_path: Optional[str] = None,
) -> Tuple[nx.MultiDiGraph, Dict[str, Any], List[str]]:
    """
    Convenience function: build graph from a corpus JSON file.

    Returns: (graph, stats, warnings)
    """
    with open(corpus_path, "r", encoding="utf-8") as f:
        schemes = json.load(f)

    corpus_version = "1.0.0"
    if manifest_path and os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
            corpus_version = manifest.get("version", "1.0.0")

    builder = KnowledgeGraphBuilder()
    graph = builder.build_from_corpus(schemes, corpus_version=corpus_version)
    return graph, builder.get_stats(), builder.get_warnings()
