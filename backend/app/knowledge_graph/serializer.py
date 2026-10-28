"""
Knowledge Graph Serializer — save and load graph snapshots.

Persists the NetworkX graph as JSON with full node/edge attributes.
Supports versioned snapshots and a 'current' pointer.
"""

import json
import os
import hashlib
import shutil
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

import networkx as nx

from app.knowledge_graph.builder import BUILDER_VERSION
from app.core.logging import get_logger

logger = get_logger(__name__)


def _graph_data_dir() -> str:
    """Get the data/graph directory path."""
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "graph"),
        os.path.join(os.getcwd(), "data", "graph"),
    ]
    for p in candidates:
        full = os.path.abspath(p)
        parent = os.path.dirname(full)
        if os.path.isdir(parent):
            return full
    return os.path.abspath(candidates[0])


def graph_to_json(graph: nx.MultiDiGraph) -> dict:
    """Serialize a NetworkX MultiDiGraph to a JSON-serializable dict."""
    nodes = []
    for node_id, attrs in sorted(graph.nodes(data=True)):
        node_data = {"id": node_id}
        node_data.update({k: v for k, v in attrs.items() if v is not None})
        nodes.append(node_data)

    edges = []
    for src, tgt, attrs in sorted(graph.edges(data=True), key=lambda e: (e[0], e[1])):
        edge_data = {"source": src, "target": tgt}
        edge_data.update({k: v for k, v in attrs.items() if v is not None})
        edges.append(edge_data)

    return {
        "graph_metadata": dict(graph.graph),
        "nodes": nodes,
        "edges": edges,
    }


def json_to_graph(data: dict) -> nx.MultiDiGraph:
    """Deserialize a JSON dict back into a NetworkX MultiDiGraph."""
    graph = nx.MultiDiGraph()

    # Restore graph-level attributes
    for k, v in data.get("graph_metadata", {}).items():
        graph.graph[k] = v

    # Restore nodes
    for node_data in data.get("nodes", []):
        node_id = node_data.pop("id")
        graph.add_node(node_id, **node_data)

    # Restore edges
    for edge_data in data.get("edges", []):
        src = edge_data.pop("source")
        tgt = edge_data.pop("target")
        graph.add_edge(src, tgt, **edge_data)

    return graph


def compute_graph_hash(graph_json: dict) -> str:
    """Compute a deterministic hash of the graph structure."""
    # Hash over sorted node IDs + sorted edge tuples
    node_ids = sorted(n["id"] for n in graph_json.get("nodes", []))
    edge_tuples = sorted(
        (e["source"], e["target"], e.get("relation", ""))
        for e in graph_json.get("edges", [])
    )
    content = json.dumps({"nodes": node_ids, "edges": edge_tuples}, sort_keys=True)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def save_graph_snapshot(
    graph: nx.MultiDiGraph,
    stats: Dict[str, Any],
    corpus_version: str = "1.0.0",
    graph_version: str = "1.0.0",
    base_dir: Optional[str] = None,
) -> str:
    """
    Save graph to snapshot and update current pointer.

    Creates:
        data/graph/snapshots/YYYY-MM-DD/graph.json
        data/graph/snapshots/YYYY-MM-DD/graph_metadata.json
        data/graph/snapshots/YYYY-MM-DD/graph_stats.json
        data/graph/current/graph.json
        data/graph/current/metadata.json

    Returns: path to the snapshot directory
    """
    base = base_dir or _graph_data_dir()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Create snapshot directory
    snapshot_dir = os.path.join(base, "snapshots", today)
    current_dir = os.path.join(base, "current")
    os.makedirs(snapshot_dir, exist_ok=True)
    os.makedirs(current_dir, exist_ok=True)

    # Serialize
    graph_json = graph_to_json(graph)
    graph_hash = compute_graph_hash(graph_json)

    # Graph metadata
    metadata = {
        "graph_version": graph_version,
        "corpus_version": corpus_version,
        "schema_version": graph.graph.get("schema_version", "1.0.0"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "node_count": stats.get("total_nodes", graph.number_of_nodes()),
        "edge_count": stats.get("total_edges", graph.number_of_edges()),
        "node_type_counts": stats.get("node_type_counts", {}),
        "edge_type_counts": stats.get("edge_type_counts", {}),
        "source_corpus_hash": "",
        "graph_hash": graph_hash,
        "builder_version": BUILDER_VERSION,
    }

    # Write snapshot files
    with open(os.path.join(snapshot_dir, "graph.json"), "w", encoding="utf-8") as f:
        json.dump(graph_json, f, indent=2, ensure_ascii=False)

    with open(os.path.join(snapshot_dir, "graph_metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    with open(os.path.join(snapshot_dir, "graph_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    # Update current/ pointer
    with open(os.path.join(current_dir, "graph.json"), "w", encoding="utf-8") as f:
        json.dump(graph_json, f, indent=2, ensure_ascii=False)

    with open(os.path.join(current_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    with open(os.path.join(current_dir, "graph_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    logger.info(f"Graph snapshot saved: {snapshot_dir}")
    logger.info(f"Current graph updated: {current_dir}")

    return snapshot_dir


def load_graph_snapshot(base_dir: Optional[str] = None) -> Tuple[nx.MultiDiGraph, dict]:
    """
    Load the current validated graph snapshot.

    Returns: (graph, metadata)
    Raises FileNotFoundError if no current graph exists.
    """
    base = base_dir or _graph_data_dir()
    current_dir = os.path.join(base, "current")

    graph_path = os.path.join(current_dir, "graph.json")
    metadata_path = os.path.join(current_dir, "metadata.json")

    if not os.path.exists(graph_path):
        raise FileNotFoundError(
            f"No current graph snapshot found at {graph_path}. "
            "Run 'python scripts/build_knowledge_graph.py' first."
        )

    with open(graph_path, "r", encoding="utf-8") as f:
        graph_json = json.load(f)

    graph = json_to_graph(graph_json)

    metadata = {}
    if os.path.exists(metadata_path):
        with open(metadata_path, "r", encoding="utf-8") as f:
            metadata = json.load(f)

    logger.info(
        f"Graph loaded: {graph.number_of_nodes()} nodes, "
        f"{graph.number_of_edges()} edges"
    )

    return graph, metadata


def export_graphml(graph: nx.MultiDiGraph, output_path: str):
    """Export graph as GraphML for visualization tools (Gephi, Cytoscape)."""
    # NetworkX GraphML doesn't support MultiDiGraph well, so convert
    # multi-edges to single edges with combined attributes
    simple = nx.DiGraph()
    for node_id, attrs in graph.nodes(data=True):
        simple.add_node(node_id, **{k: str(v) for k, v in attrs.items() if v is not None})

    for src, tgt, attrs in graph.edges(data=True):
        label = attrs.get("relation", "")
        if not simple.has_edge(src, tgt):
            simple.add_edge(src, tgt, label=label, relation=label)

    nx.write_graphml(simple, output_path)
    logger.info(f"GraphML exported to {output_path}")
