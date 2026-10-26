"""
Metric helpers for Phase 7 evaluation.

All functions are pure. Definitions are documented in docs/phase7-metrics.md.
"""

import math
from typing import Iterable, List, Optional, Sequence, Set, Dict, Any


def safe_ratio(numerator: float, denominator: float) -> Optional[float]:
    """numerator / denominator, or None when the denominator is zero (metric undefined)."""
    if not denominator:
        return None
    return round(numerator / denominator, 4)


def precision_recall_f1(predicted: Iterable[str], expected: Iterable[str]) -> Dict[str, Optional[float]]:
    """Set-based precision, recall and F1."""
    pred: Set[str] = set(predicted)
    exp: Set[str] = set(expected)
    tp = len(pred & exp)
    precision = safe_ratio(tp, len(pred))
    recall = safe_ratio(tp, len(exp))
    if precision is None or recall is None or (precision + recall) == 0:
        f1 = None if precision is None or recall is None else 0.0
    else:
        f1 = round(2 * precision * recall / (precision + recall), 4)
    return {"precision": precision, "recall": recall, "f1": f1, "tp": tp,
            "fp": len(pred - exp), "fn": len(exp - pred)}


def precision_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> Optional[float]:
    """Fraction of the top-k ranked items that are relevant."""
    top = list(ranked)[:k]
    if not top:
        return None
    rel = set(relevant)
    return round(sum(1 for r in top if r in rel) / len(top), 4)


def recall_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> Optional[float]:
    """Fraction of relevant items that appear in the top-k ranked items."""
    rel = set(relevant)
    if not rel:
        return None
    top = set(list(ranked)[:k])
    return round(len(rel & top) / len(rel), 4)


def percentile(values: Sequence[float], pct: float) -> Optional[float]:
    """Nearest-rank percentile (pct in 0..100). None for empty input."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100.0 * len(ordered)))
    return round(ordered[rank - 1], 3)


def latency_summary(values_ms: Sequence[float]) -> Dict[str, Any]:
    """count / mean / P50 / P95 / max for a latency sample in milliseconds."""
    if not values_ms:
        return {"count": 0, "mean_ms": None, "p50_ms": None, "p95_ms": None, "max_ms": None}
    return {
        "count": len(values_ms),
        "mean_ms": round(sum(values_ms) / len(values_ms), 3),
        "p50_ms": percentile(values_ms, 50),
        "p95_ms": percentile(values_ms, 95),
        "max_ms": round(max(values_ms), 3),
    }


def mean(values: Sequence[float]) -> Optional[float]:
    values = [v for v in values if v is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def summarize_checks(checks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize a list of {'id', 'passed', ...} check records."""
    total = len(checks)
    passed = sum(1 for c in checks if c.get("passed"))
    return {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": safe_ratio(passed, total),
        "failures": [c for c in checks if not c.get("passed")],
    }
