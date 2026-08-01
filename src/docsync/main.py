"""Docsync application entry point."""

from __future__ import annotations

import asyncio
import sys

from docsync.config import Settings
from docsync.crawler import run_crawler
from docsync.logging_config import configure_logging
from docsync.metrics import CrawlStats


def run() -> int:
    """Initialize docsync and execute the crawler."""

    try:
        settings = Settings.from_environment()
        logger = configure_logging(settings.log_dir)

        logger.info("Docsync initialized successfully.")
        logger.info("Start URL: %s", settings.start_url)
        logger.info("Output directory: %s", settings.output_dir)
        logger.info("State directory: %s", settings.state_dir)
        logger.info("Language: %s", settings.language)
        logger.info("Maximum concurrency: %d", settings.max_concurrency)
        logger.info("Maximum requests: %d", settings.max_requests)
        logger.info(
            "robots.txt support enabled: %s",
            settings.respect_robots_txt,
        )

        stats = asyncio.run(run_crawler(settings.start_url))
        if isinstance(stats, CrawlStats):
            logger.info(stats.finished_summary())
            return int(stats.exit_code)
    except (OSError, ValueError) as error:
        print(f"Docsync startup failed: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Docsync interrupted by user.", file=sys.stderr)
        return 130

    return 0


def main() -> int:
    """Run the canonical docsync command-line entry point."""

    return run()
