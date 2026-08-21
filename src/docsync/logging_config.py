"""Logging configuration."""

from __future__ import annotations

import logging
from pathlib import Path


def configure_logging(log_dir: Path) -> logging.Logger:
    """Configure console and file logging."""

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "docsync.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.WARNING)
    root_logger.handlers.clear()

    docsync_logger = logging.getLogger("docsync")
    docsync_logger.setLevel(logging.INFO)

    crawlee_logger = logging.getLogger("crawlee")
    crawlee_logger.handlers.clear()
    crawlee_logger.setLevel(logging.WARNING)
    crawlee_logger.propagate = False

    autoscaling_logger = logging.getLogger("crawlee._autoscaling")
    autoscaling_logger.handlers.clear()
    autoscaling_logger.setLevel(logging.WARNING)
    autoscaling_logger.propagate = False

    crawler_logger = logging.getLogger("BeautifulSoupCrawler")
    crawler_logger.handlers.clear()
    crawler_logger.setLevel(logging.WARNING)
    crawler_logger.propagate = False

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(
        log_file,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)

    return docsync_logger
