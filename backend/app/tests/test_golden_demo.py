"""
Golden demo scenarios (Phase 8 Step 11) as an integration test.

Runs evaluation/datasets/demo_scenarios.json through the real FastAPI routes
and LangGraph pipeline with external services mocked and the corpus-backed DB
fixture (the fixture is verified against PostgreSQL by scripts/verify_db_parity.py).
Also runs the Phase 7 E2E golden journeys so they stay a permanent regression suite (§133).
"""

import logging
import os
import sys

import pytest

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)


@pytest.fixture(scope="module")
def corpus_db():
    import evaluation  # noqa: F401
    from evaluation.fixtures.corpus_db import CorpusDB
    return CorpusDB()


@pytest.mark.parametrize("dataset", ["demo_scenarios.json", "e2e_cases.json"])
def test_golden_journeys(corpus_db, dataset):
    from evaluation.runners import e2e_runner
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        result = e2e_runner.run(corpus_db, dataset=dataset)
    finally:
        logging.disable(previous)
    assert result["failed"] == 0, result["failures"]
    assert result["total"] >= 12
