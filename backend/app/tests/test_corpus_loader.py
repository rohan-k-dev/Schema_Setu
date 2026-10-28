"""
Tests for corpus loader.
"""

import pytest
import json
import os
import tempfile

from app.ingestion import CanonicalScheme, SourceRecord, SourceType, SchemeLevel
from app.ingestion.corpus_loader import SchemeCorpusLoader


def _create_test_corpus(tmp_path):
    """Create a small test corpus file and return its path."""
    schemes = [
        {
            "scheme_id": "PM_KISAN",
            "name": "Pradhan Mantri Kisan Samman Nidhi",
            "short_name": "PM-KISAN",
            "aliases": ["PM Kisan", "PM-KISAN"],
            "description": "Income support scheme.",
            "level": "central",
            "status": "ACTIVE",
            "applicable_states": None,
            "applicable_crops": None,
            "target_beneficiaries": ["farmers"],
            "source_records": [{"source_id": "TEST", "source_type": "OFFICIAL_CENTRAL"}],
        },
        {
            "scheme_id": "STATE_KA_RAITHA",
            "name": "Raitha Siri Karnataka",
            "description": "Karnataka farmer support.",
            "level": "state",
            "status": "ACTIVE",
            "applicable_states": ["Karnataka"],
            "applicable_crops": ["ragi", "rice"],
            "target_beneficiaries": ["farmers"],
            "source_records": [{"source_id": "TEST", "source_type": "OFFICIAL_STATE"}],
        },
        {
            "scheme_id": "PMFBY",
            "name": "Pradhan Mantri Fasal Bima Yojana",
            "short_name": "PMFBY",
            "aliases": ["Crop Insurance"],
            "description": "Crop insurance scheme.",
            "level": "central",
            "status": "ACTIVE",
            "applicable_states": None,
            "applicable_crops": ["rice", "wheat", "cotton"],
            "target_beneficiaries": ["farmers"],
            "source_records": [{"source_id": "TEST", "source_type": "OFFICIAL_CENTRAL"}],
        },
    ]
    path = os.path.join(str(tmp_path), "test_schemes.json")
    with open(path, "w") as f:
        json.dump(schemes, f)
    return path


class TestCorpusLoader:
    """Test corpus loading and searching."""

    def test_load(self, tmp_path):
        path = _create_test_corpus(tmp_path)
        loader = SchemeCorpusLoader(corpus_path=path)
        count = loader.load()
        assert count == 3
        assert loader.is_loaded
        assert loader.scheme_count == 3

    def test_get_by_id(self, tmp_path):
        path = _create_test_corpus(tmp_path)
        loader = SchemeCorpusLoader(corpus_path=path)
        loader.load()
        scheme = loader.get_by_id("PM_KISAN")
        assert scheme is not None
        assert scheme.name == "Pradhan Mantri Kisan Samman Nidhi"

    def test_get_by_id_case_insensitive(self, tmp_path):
        path = _create_test_corpus(tmp_path)
        loader = SchemeCorpusLoader(corpus_path=path)
        loader.load()
        scheme = loader.get_by_id("pm_kisan")
        assert scheme is not None

    def test_get_by_id_not_found(self, tmp_path):
        path = _create_test_corpus(tmp_path)
        loader = SchemeCorpusLoader(corpus_path=path)
        loader.load()
        assert loader.get_by_id("NONEXISTENT") is None

    def test_search_by_name(self, tmp_path):
        path = _create_test_corpus(tmp_path)
        loader = SchemeCorpusLoader(corpus_path=path)
        loader.load()
        results = loader.search_by_name("Kisan")
        assert len(results) >= 1
        assert any(s.scheme_id == "PM_KISAN" for s in results)

    def test_search_by_alias(self, tmp_path):
        path = _create_test_corpus(tmp_path)
        loader = SchemeCorpusLoader(corpus_path=path)
        loader.load()
        results = loader.search_by_name("Crop Insurance")
        assert len(results) == 1
        assert results[0].scheme_id == "PMFBY"

    def test_search_by_state(self, tmp_path):
        path = _create_test_corpus(tmp_path)
        loader = SchemeCorpusLoader(corpus_path=path)
        loader.load()
        results = loader.search_by_state("Karnataka")
        # Should include Karnataka-specific AND central schemes (no state restriction)
        ids = {s.scheme_id for s in results}
        assert "STATE_KA_RAITHA" in ids
        assert "PM_KISAN" in ids  # Central, no state restriction

    def test_search_by_crop(self, tmp_path):
        path = _create_test_corpus(tmp_path)
        loader = SchemeCorpusLoader(corpus_path=path)
        loader.load()
        results = loader.search_by_crop("ragi")
        ids = {s.scheme_id for s in results}
        assert "STATE_KA_RAITHA" in ids
        assert "PM_KISAN" in ids  # No crop restriction

    def test_combined_search(self, tmp_path):
        path = _create_test_corpus(tmp_path)
        loader = SchemeCorpusLoader(corpus_path=path)
        loader.load()
        results = loader.search(state="Karnataka", crop="ragi")
        ids = {s.scheme_id for s in results}
        assert "STATE_KA_RAITHA" in ids
        assert "PM_KISAN" in ids

    def test_combined_search_with_query(self, tmp_path):
        path = _create_test_corpus(tmp_path)
        loader = SchemeCorpusLoader(corpus_path=path)
        loader.load()
        results = loader.search(query="Bima")
        assert len(results) == 1
        assert results[0].scheme_id == "PMFBY"

    def test_to_dicts_backward_compat(self, tmp_path):
        path = _create_test_corpus(tmp_path)
        loader = SchemeCorpusLoader(corpus_path=path)
        loader.load()
        dicts = loader.to_dicts()
        assert len(dicts) == 3
        assert "title" in dicts[0]
        assert "scheme_id" in dicts[0]
        assert "source" in dicts[0]
        assert dicts[0]["source"] == "local_corpus"

    def test_missing_file_loads_empty(self, tmp_path):
        loader = SchemeCorpusLoader(corpus_path=os.path.join(str(tmp_path), "nonexistent.json"))
        count = loader.load()
        assert count == 0
        assert loader.is_loaded
        assert loader.scheme_count == 0
