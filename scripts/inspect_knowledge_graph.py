"""
CLI: Inspect Knowledge Graph — explore nodes, edges, neighbors.

Usage:
  python scripts/inspect_knowledge_graph.py                     # Show overview
  python scripts/inspect_knowledge_graph.py --scheme PM_KISAN   # Inspect a scheme
  python scripts/inspect_knowledge_graph.py --node-types        # List node types
  python scripts/inspect_knowledge_graph.py --edge-types        # List edge types
  python scripts/inspect_knowledge_graph.py --stats             # Show statistics
"""

import sys
import os
import json
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.knowledge_graph.serializer import load_graph_snapshot
from app.knowledge_graph.repository import KnowledgeGraphRepository
from app.knowledge_graph.schema import NodeType, EdgeType


def main():
    parser = argparse.ArgumentParser(description="Inspect Knowledge Graph")
    parser.add_argument("--scheme", type=str, help="Inspect a specific scheme by ID")
    parser.add_argument("--node-types", action="store_true", help="List node types")
    parser.add_argument("--edge-types", action="store_true", help="List edge types")
    parser.add_argument("--stats", action="store_true", help="Show graph statistics")
    parser.add_argument("--node", type=str, help="Inspect a specific node by full ID")
    args = parser.parse_args()

    try:
        graph, metadata = load_graph_snapshot()
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    repo = KnowledgeGraphRepository(graph, metadata)

    if args.node_types:
        _show_node_types(graph)
    elif args.edge_types:
        _show_edge_types(graph)
    elif args.stats:
        _show_stats(graph, metadata)
    elif args.scheme:
        _inspect_scheme(repo, args.scheme)
    elif args.node:
        _inspect_node(repo, args.node)
    else:
        _show_overview(graph, metadata)


def _show_overview(graph, metadata):
    print(f"Knowledge Graph Overview")
    print(f"========================")
    print(f"  Nodes: {graph.number_of_nodes()}")
    print(f"  Edges: {graph.number_of_edges()}")
    print(f"  Corpus version: {metadata.get('corpus_version', '?')}")
    print(f"  Graph version: {metadata.get('graph_version', '?')}")
    print(f"  Generated: {metadata.get('generated_at', '?')}")
    print()
    _show_node_types(graph)
    print()
    _show_edge_types(graph)


def _show_node_types(graph):
    counts = {}
    for _, attrs in graph.nodes(data=True):
        nt = attrs.get("node_type", "UNKNOWN")
        counts[nt] = counts.get(nt, 0) + 1

    print("Node Types:")
    for nt, count in sorted(counts.items()):
        print(f"  {nt}: {count}")


def _show_edge_types(graph):
    counts = {}
    for _, _, attrs in graph.edges(data=True):
        et = attrs.get("relation", "UNKNOWN")
        counts[et] = counts.get(et, 0) + 1

    print("Edge Types:")
    for et, count in sorted(counts.items()):
        print(f"  {et}: {count}")


def _show_stats(graph, metadata):
    print(f"Graph Statistics")
    print(f"================")
    ntc = metadata.get("node_type_counts", {})
    etc = metadata.get("edge_type_counts", {})

    print(f"  Nodes: {graph.number_of_nodes()}")
    print(f"  Edges: {graph.number_of_edges()}")
    if ntc:
        print(f"\n  Node types: {json.dumps(ntc, indent=4)}")
    if etc:
        print(f"\n  Edge types: {json.dumps(etc, indent=4)}")


def _inspect_scheme(repo, scheme_id):
    node = repo.get_scheme_node(scheme_id)
    if not node:
        print(f"Scheme not found: {scheme_id}")
        print(f"  Available schemes:")
        for sid in sorted(repo.get_nodes_by_type(NodeType.SCHEME))[:10]:
            attrs = repo.get_node(sid)
            print(f"    {sid} — {attrs.get('name', '')}")
        sys.exit(1)

    print(f"SCHEME: {scheme_id}")
    print(f"  Name: {node.get('name', '')}")
    print(f"  Status: {node.get('status', '')}")
    print(f"  Level: {node.get('level', '')}")
    print(f"  Ministry: {node.get('ministry', '')}")
    print()

    # Show neighbors grouped by relationship
    full_id = f"SCHEME:{scheme_id}"
    neighbors = repo.get_neighbors(full_id)

    by_relation = {}
    for n in neighbors:
        rel = n["relation"]
        if rel not in by_relation:
            by_relation[rel] = []
        by_relation[rel].append(n)

    for rel in sorted(by_relation.keys()):
        items = by_relation[rel]
        print(f"  {rel}:")
        for item in items:
            name = item["attributes"].get("canonical_name",
                   item["attributes"].get("name",
                   item["attributes"].get("field_name", item["node_id"])))
            extra = ""
            if item["attributes"].get("node_type") == "ELIGIBILITY_RULE":
                op = item["attributes"].get("operator", "")
                val = item["attributes"].get("value", "")
                extra = f" ({op} {val})"
            print(f"    -> {name}{extra}")
    print()


def _inspect_node(repo, node_id):
    node = repo.get_node(node_id)
    if not node:
        print(f"Node not found: {node_id}")
        sys.exit(1)

    print(f"Node: {node_id}")
    for k, v in sorted(node.items()):
        print(f"  {k}: {v}")
    print()

    neighbors = repo.get_neighbors(node_id)
    if neighbors:
        print(f"  Outgoing:")
        for n in neighbors:
            print(f"    --{n['relation']}--> {n['node_id']}")


if __name__ == "__main__":
    main()
