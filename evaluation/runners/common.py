"""
Shared helpers for evaluation runners.
"""

import json
import os
import uuid
import wave
import io
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from evaluation import DATASETS_DIR, DATA_EVAL_DIR


def load_dataset(name: str) -> Any:
    """Load a dataset from evaluation/datasets/ (canonical location)."""
    with open(os.path.join(DATASETS_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def load_legacy(name: str) -> Any:
    """Load a Phase 5/6 dataset kept in data/evaluation/ (not duplicated)."""
    with open(os.path.join(DATA_EVAL_DIR, name), encoding="utf-8") as f:
        return json.load(f)


@dataclass
class DatasetRule:
    """Adapter giving dataset rule dicts the attribute shape of EligibilityRuleRow."""
    field_name: str
    operator: str
    value_json: Any = None
    logical_group: str = "AND"
    required: bool = True
    source_text: Optional[str] = None
    unit: Optional[str] = None
    rule_id: Optional[str] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "DatasetRule":
        return cls(
            field_name=d["field_name"],
            operator=d["operator"],
            value_json=d.get("value_json"),
            logical_group=d.get("logical_group") or "AND",
            required=d.get("required", True),
            source_text=d.get("source_text"),
            unit=d.get("unit"),
            rule_id=d.get("rule_id"),
        )


def rules_from(dicts: List[Dict[str, Any]]) -> List[DatasetRule]:
    return [DatasetRule.from_dict(d) for d in dicts]


def new_thread(prefix: str) -> str:
    return f"eval-{prefix}-{uuid.uuid4().hex[:8]}"


def make_wav(tag: str) -> bytes:
    """A small, valid 16 kHz mono WAV whose payload embeds `tag` (used as mock-ASR key)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        payload = (tag.encode("utf-8") + b"\x00" * 3200)[:3200]
        w.writeframes(payload)
    return buf.getvalue()


def get_client():
    """FastAPI TestClient without lifespan (no PostgreSQL connection is attempted)."""
    from fastapi.testclient import TestClient
    from app.main import app
    return TestClient(app)


def graph_state(thread_id: str) -> Dict[str, Any]:
    """Final LangGraph state values for a thread (for structured assertions)."""
    from app.graph.workflow import kisan_agent
    snap = kisan_agent.get_state({"configurable": {"thread_id": thread_id}})
    return dict(snap.values or {})


def scheme_map(response_json: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """scheme_id -> scheme dict from a ChatResponse JSON."""
    return {s.get("scheme_id"): s for s in (response_json.get("schemes") or []) if s.get("scheme_id")}


def check(case_id: str, passed: bool, **details) -> Dict[str, Any]:
    rec = {"id": case_id, "passed": bool(passed)}
    rec.update(details)
    return rec


def num_equal(a: Any, b: Any) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-6
    except (TypeError, ValueError):
        return False


def value_matches(actual: Any, expected: Any) -> bool:
    """Lenient value comparison: numbers by value, strings case-insensitively."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        return actual == expected
    if isinstance(expected, (int, float)):
        return num_equal(actual, expected)
    if isinstance(expected, str) and isinstance(actual, str):
        return actual.strip().lower() == expected.strip().lower()
    return actual == expected


def strict_value_matches(actual: Any, expected: Any) -> bool:
    """Exact comparison for canonicalisation tests (strings case-sensitive)."""
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return num_equal(actual, expected)
    return actual == expected
