#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path


PIPELINE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PIPELINE_ROOT.parent

DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "output"
OUTPUT_ROOT = (
    Path(os.environ.get("DOCSYNC_OUTPUT_ROOT", DEFAULT_OUTPUT_ROOT))
    .expanduser()
    .resolve()
)

STATE_ROOT = PROJECT_ROOT / "state"
DOCS_PIPELINE_RUNNER = PIPELINE_ROOT / "docs_pipeline_runner.py"


__all__ = [
    "DEFAULT_OUTPUT_ROOT",
    "DOCS_PIPELINE_RUNNER",
    "OUTPUT_ROOT",
    "PIPELINE_ROOT",
    "PROJECT_ROOT",
    "STATE_ROOT",
]
