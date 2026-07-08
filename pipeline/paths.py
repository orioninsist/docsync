#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PIPELINE_ROOT.parent

OUTPUT_ROOT = PROJECT_ROOT / "output"
STATE_ROOT = PROJECT_ROOT / "state"
DOCS_PIPELINE_RUNNER = PIPELINE_ROOT / "docs_pipeline_runner.py"


__all__ = [
    "DOCS_PIPELINE_RUNNER",
    "OUTPUT_ROOT",
    "PIPELINE_ROOT",
    "PROJECT_ROOT",
    "STATE_ROOT",
]
