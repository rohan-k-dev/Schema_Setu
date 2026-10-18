"""
CLI: Validate an existing Knowledge Graph snapshot.

Usage:
  python scripts/validate_knowledge_graph.py
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.knowledge_graph.serializer import load_graph_snapshot
from app.knowledge_graph.validator import validate_graph, calculate_coverage_metrics


def find_corpus_path():
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "data", "validated", "schemes.json"),
        os.path.join(os.getcwd(), "data", "validated", "schemes.json"),
    ]
    for p in candidates:
        full = os.path.abspath(p)
        if os.path.exists(full):
            return full
    return None


def main():
    print("Loading current graph snapshot...")
    try:
        graph, metadata = load_graph_snapshot()
    except FileNotFoundError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    print(f"Nodes: {graph.number_of_nodes()}")
    print(f"Edges: {graph.number_of_edges()}")
    print(f"Corpus version: {metadata.get('corpus_version', '?')}")
    print(f"Graph version: {metadata.get('graph_version', '?')}")

    # Load corpus for consistency check
    corpus_path = find_corpus_path()
    scheme_ids = None
    if corpus_path:
        with open(corpus_path, "r", encoding="utf-8") as f:
            schemes = json.load(f)
            scheme_ids = [s["scheme_id"] for s in schemes]
        print(f"Corpus schemes: {len(scheme_ids)}")

    # Validate
    result = validate_graph(graph, corpus_scheme_ids=scheme_ids)

    print(f"\n{result.summary()}")

    if result.errors:
        print(f"\nErrors:")
        for e in result.errors:
            print(f"  ✗ {e}")

    if result.warnings:
        print(f"\nWarnings:")
        for w in result.warnings:
            print(f"  ⚠ {w}")

    # Coverage
    coverage = calculate_coverage_metrics(graph)
    print(f"\nCoverage:")
    for key, val in coverage.items():
        print(f"  {key}: {val}%")

    # Machine-readable report
    report = {
        "validation": result.to_dict(),
        "coverage": coverage,
        "metadata": metadata,
    }

    # Save report next to graph
    report_path = os.path.join(
        os.path.dirname(__file__), "..", "data", "graph", "current", "validation_report.json"
    )
    report_path = os.path.abspath(report_path)
    if os.path.isdir(os.path.dirname(report_path)):
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nReport saved: {report_path}")

    sys.exit(0 if result.is_valid else 1)


if __name__ == "__main__":
    main()
