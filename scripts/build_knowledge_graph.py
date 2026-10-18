"""
CLI: Build Knowledge Graph from validated corpus.

Usage:
  python scripts/build_knowledge_graph.py              # Full build
  python scripts/build_knowledge_graph.py --dry-run    # Preview only
  python scripts/build_knowledge_graph.py --force      # Overwrite existing
  python scripts/build_knowledge_graph.py --graphml    # Also export GraphML
"""

import sys
import os
import json
import argparse
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.knowledge_graph.builder import KnowledgeGraphBuilder, build_graph_from_corpus_file
from app.knowledge_graph.serializer import save_graph_snapshot, export_graphml
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


def find_manifest_path():
    candidates = [
        os.path.join(os.path.dirname(__file__), "..", "data", "metadata", "corpus_manifest.json"),
        os.path.join(os.getcwd(), "data", "metadata", "corpus_manifest.json"),
    ]
    for p in candidates:
        full = os.path.abspath(p)
        if os.path.exists(full):
            return full
    return None


def main():
    parser = argparse.ArgumentParser(description="Build Knowledge Graph from validated corpus")
    parser.add_argument("--dry-run", action="store_true", help="Preview without saving")
    parser.add_argument("--force", action="store_true", help="Overwrite existing snapshot")
    parser.add_argument("--graphml", action="store_true", help="Also export GraphML")
    parser.add_argument("--corpus", type=str, help="Path to schemes.json")
    args = parser.parse_args()

    # Find corpus
    corpus_path = args.corpus or find_corpus_path()
    if not corpus_path:
        print("ERROR: Validated corpus not found. Run 'python scripts/build_corpus.py' first.")
        sys.exit(1)

    manifest_path = find_manifest_path()

    print(f"Corpus: {corpus_path}")
    print(f"Manifest: {manifest_path or '(not found)'}")

    # Load corpus
    with open(corpus_path, "r", encoding="utf-8") as f:
        schemes = json.load(f)

    corpus_version = "1.0.0"
    if manifest_path:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
            corpus_version = manifest.get("version", "1.0.0")

    print(f"Schemes: {len(schemes)}")
    print(f"Corpus version: {corpus_version}")

    # Build graph
    print("\nBuilding Knowledge Graph...")
    start = time.time()

    builder = KnowledgeGraphBuilder()
    graph = builder.build_from_corpus(schemes, corpus_version=corpus_version)
    stats = builder.get_stats()
    warnings = builder.get_warnings()

    build_time = time.time() - start

    # Print summary
    print(f"\nKnowledge Graph Build")
    print(f"=====================")
    print(f"Corpus version: {corpus_version}")
    print()

    ntc = stats.get("node_type_counts", {})
    for nt in ["SCHEME", "STATE", "DISTRICT", "CROP", "BENEFICIARY", "CATEGORY",
                "OCCUPATION", "GENDER", "MINISTRY", "DEPARTMENT", "BENEFIT",
                "DOCUMENT", "ELIGIBILITY_RULE", "SOURCE", "COUNTRY"]:
        count = ntc.get(nt, 0)
        if count > 0:
            print(f"  {nt}: {count}")

    print(f"\n  Total Nodes: {stats['total_nodes']}")
    print(f"  Total Edges: {stats['total_edges']}")
    print(f"  Connected Components: {stats.get('connected_components', '?')}")
    print(f"  Build Time: {build_time:.3f}s")

    if warnings:
        print(f"\n  Warnings: {len(warnings)}")
        for w in warnings[:10]:
            print(f"    - {w}")

    # Validate
    print("\nValidating...")
    scheme_ids = [s["scheme_id"] for s in schemes]
    result = validate_graph(graph, corpus_scheme_ids=scheme_ids)
    print(f"\n{result.summary()}")

    if result.errors:
        for e in result.errors[:10]:
            print(f"  ERROR: {e}")
    if result.warnings:
        for w in result.warnings[:10]:
            print(f"  WARN: {w}")

    # Coverage
    coverage = calculate_coverage_metrics(graph)
    print(f"\nCoverage:")
    for key, val in coverage.items():
        print(f"  {key}: {val}%")

    if args.dry_run:
        print(f"\n[DRY RUN] Graph NOT saved.")
        return

    # Save
    print(f"\nSaving snapshot...")
    start = time.time()
    snapshot_dir = save_graph_snapshot(
        graph, stats,
        corpus_version=corpus_version,
        graph_version="1.0.0",
    )
    save_time = time.time() - start
    print(f"Snapshot saved: {snapshot_dir}")
    print(f"Save time: {save_time:.3f}s")

    # Optional GraphML
    if args.graphml:
        graphml_path = os.path.join(snapshot_dir, "graph.graphml")
        export_graphml(graph, graphml_path)
        print(f"GraphML exported: {graphml_path}")

    print(f"\n[OK] Knowledge Graph build complete!")


if __name__ == "__main__":
    main()
