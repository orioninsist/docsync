"""Typed runtime dependency context for crawler orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from crawler.config import CrawlerConfig
from crawler.database import DatabaseManager


@dataclass(frozen=True, slots=True)
class CrawlerRuntimeContext:
    """Provide typed crawler dependencies without owning their construction."""

    output_dir: Path
    database: DatabaseManager
    logger: logging.Logger
    config: CrawlerConfig
