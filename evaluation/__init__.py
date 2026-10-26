"""
SchemeSetu Phase 7 evaluation package.

Layout:
    datasets/   — canonical, human-curated golden datasets (versioned)
    fixtures/   — offline fixtures: corpus-backed DB, mocked LLM / Tavily / Sarvam
    metrics/    — metric helpers (precision/recall/F1, percentiles, ...)
    runners/    — one runner per evaluation area; each returns a JSON-able dict
    reports/    — notes on report locations (generated reports live in data/evaluation/reports/)

Entry point: scripts/run_evaluation.py
"""

import os
import sys

EVALUATION_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(EVALUATION_DIR)
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
DATASETS_DIR = os.path.join(EVALUATION_DIR, "datasets")
DATA_EVAL_DIR = os.path.join(PROJECT_ROOT, "data", "evaluation")
REPORTS_DIR = os.path.join(DATA_EVAL_DIR, "reports")
CORPUS_PATH = os.path.join(PROJECT_ROOT, "data", "validated", "schemes.json")

if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)
