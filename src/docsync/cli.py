"""Plain-text command line interface for DocsSync."""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from playwright.sync_api import sync_playwright

from docsync.crawler import run_crawler


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return number


def _ensure_browser() -> None:
    """Install DocsSync's Chromium runtime on first use when it is missing."""
    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)
    if executable.exists():
        return

    print("docsync: preparing browser runtime (first run only)...")
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docsync",
        description="Synchronize documentation to Markdown with Crawlee Python.",
    )
    parser.add_argument("url", help="Documentation start URL")
    parser.add_argument("--language", default="en", help="Language code (default: en)")
    parser.add_argument("--output-dir", type=Path, default=Path("docs"))
    parser.add_argument("--state-dir", type=Path, default=Path("storage/docsync"))
    parser.add_argument("--max-concurrency", type=_positive, default=5)
    parser.add_argument("--max-requests", type=_positive, default=10_000)
    parser.add_argument("--requests-per-minute", type=_positive, default=120)
    parser.add_argument(
        "--refresh-hours",
        type=int,
        default=24,
        help="Skip recently synchronized URLs for this many hours; 0 always checks",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.refresh_hours < 0:
        raise SystemExit("--refresh-hours cannot be negative")

    _ensure_browser()

    result = asyncio.run(
        run_crawler(
            start_url=args.url,
            output_dir=args.output_dir,
            state_dir=args.state_dir,
            language=args.language,
            max_concurrency=args.max_concurrency,
            max_requests=args.max_requests,
            requests_per_minute=args.requests_per_minute,
            refresh_hours=args.refresh_hours,
        )
    )

    print(
        "done "
        f"processed={result['processed']} "
        f"saved={result['saved']} "
        f"unchanged={result['unchanged']} "
        f"skipped={result['skipped']}"
    )
    return 0
