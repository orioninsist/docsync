from __future__ import annotations

import argparse
import asyncio
import inspect
import os
from collections.abc import Awaitable, Sequence
from pathlib import Path
from typing import Any

from docsync.config import Settings
from docsync.crawler import run_crawler
from docsync.inventory import run_inventory
from docsync.metrics import CrawlStats
from docsync.progress_events import CrawlEvent
from docsync.terminal_ui import (
    CrawlDashboard,
    CrawlProgressSnapshot,
    SiteInformation,
    build_console,
)


def positive_integer(value: str) -> int:
    """Parse a strictly positive integer for argparse."""

    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"expected a positive integer, received {value!r}"
        ) from error

    if parsed < 1:
        raise argparse.ArgumentTypeError(
            f"expected a positive integer, received {value!r}"
        )

    return parsed


def build_parser() -> argparse.ArgumentParser:
    """Create the docsync command-line parser without side effects."""

    parser = argparse.ArgumentParser(
        prog="docsync",
        description="Crawl documentation pages and synchronize Markdown output.",
    )
    parser.add_argument(
        "start_url",
        nargs="?",
        default=os.environ.get(
            "DOCSYNC_START_URL",
            "https://www.etsy.com/seller-handbook",
        ),
        help="Initial URL to crawl.",
    )
    parser.add_argument(
        "--output-dir",
        "--output-folder",
        type=Path,
        default=None,
        help="Directory for generated Markdown files.",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="Directory for persistent crawler state.",
    )
    parser.add_argument(
        "--max-concurrency",
        type=positive_integer,
        default=None,
        help="Maximum number of concurrent crawler tasks.",
    )
    parser.add_argument(
        "--max-requests",
        type=positive_integer,
        default=None,
        help="Maximum number of requests for this crawl.",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Preferred document language.",
    )
    parser.add_argument(
        "--refresh-hours",
        type=int,
        default=None,
        help=(
            "Do not request URLs saved successfully within this many hours. "
            "Use 0 to disable the refresh window."
        ),
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        default=None,
        help="Ignore incremental URL state and request pages again.",
    )
    parser.add_argument(
        "--mode",
        choices=(
            "http",
            "playwright",
        ),
        default=None,
        help="Crawler mode. Use 'playwright' for JavaScript-rendered pages.",
    )
    parser.add_argument(
        "--javascript",
        "--browser",
        "--playwright",
        dest="mode",
        action="store_const",
        const="playwright",
        help="Use Playwright for JavaScript-rendered pages.",
    )
    parser.add_argument(
        "--show-browser",
        dest="headless",
        action="store_false",
        default=None,
        help="Show the browser window in Playwright mode.",
    )
    parser.add_argument(
        "--browser-type",
        choices=(
            "chromium",
            "firefox",
            "webkit",
        ),
        default=None,
        help="Playwright browser engine. Default: chromium.",
    )
    parser.add_argument(
        "--requests-per-minute",
        type=positive_integer,
        default=None,
        help="Maximum requests per minute. Overrides DOCSYNC_REQUESTS_PER_MINUTE.",
    )
    parser.add_argument(
        "--inventory-only",
        action="store_true",
        help=(
            "Discover and classify in-scope URLs without writing Markdown. "
            "Writes site-inventory.json to --state-dir."
        ),
    )

    return parser


def _apply_environment_overrides(args: argparse.Namespace) -> None:
    overrides: dict[str, object | None] = {
        "DOCSYNC_START_URL": args.start_url,
        "DOCSYNC_OUTPUT_DIR": args.output_dir,
        "DOCSYNC_STATE_DIR": args.state_dir,
        "DOCSYNC_MAX_CONCURRENCY": args.max_concurrency,
        "DOCSYNC_MAX_REQUESTS": args.max_requests,
        "DOCSYNC_LANGUAGE": args.language,
        "DOCSYNC_MODE": args.mode,
        "DOCSYNC_HEADLESS": args.headless,
        "DOCSYNC_BROWSER_TYPE": args.browser_type,
    }

    for name, value in overrides.items():
        if value is not None:
            os.environ[name] = str(value)

    if getattr(args, "requests_per_minute", None) is not None:
        os.environ["DOCSYNC_REQUESTS_PER_MINUTE"] = str(args.requests_per_minute)


def _resolve_crawler_result(result: Any) -> Any:
    """Execute awaitable crawler results while preserving synchronous support."""

    if inspect.isawaitable(result):
        return asyncio.run(_await_crawler_result(result))

    return result


def _invoke_run_crawler(args: argparse.Namespace) -> Any:
    signature = inspect.signature(run_crawler)
    parameters = signature.parameters

    supported_values: dict[str, object] = {
        "start_url": args.start_url,
        "output_dir": args.output_dir,
        "state_dir": args.state_dir,
        "max_concurrency": args.max_concurrency,
        "max_requests": args.max_requests,
        "language": args.language,
        "refresh_hours": args.refresh_hours,
        "force_refresh": args.force_refresh,
        "mode": args.mode,
        "headless": args.headless,
        "browser_type": args.browser_type,
        "event_sink": getattr(
            args,
            "_docsync_event_sink",
            None,
        ),
    }

    keyword_arguments = {
        name: supported_values[name]
        for name in parameters
        if name in supported_values and supported_values[name] is not None
    }

    if not parameters:
        return _resolve_crawler_result(run_crawler())

    if set(parameters) == {"start_url"}:
        return _resolve_crawler_result(run_crawler(args.start_url))

    if keyword_arguments:
        return _resolve_crawler_result(run_crawler(**keyword_arguments))

    if len(parameters) == 1:
        parameter = next(iter(parameters.values()))
        annotation_text = str(parameter.annotation).lower()

        if "setting" in parameter.name.lower() or "setting" in annotation_text:
            settings = Settings.from_environment()
            return _resolve_crawler_result(run_crawler(settings))

    detected = ", ".join(parameters) or "<none>"
    raise RuntimeError(
        f"Unsupported run_crawler() signature. Detected parameters: {detected}"
    )


async def _await_crawler_result(awaitable: Awaitable[Any]) -> Any:
    """Convert an arbitrary awaitable into a native coroutine."""

    return await awaitable


def _build_dashboard(settings: Settings) -> CrawlDashboard:
    """Create the canonical CLI dashboard from resolved runtime settings."""

    site = SiteInformation.from_start_url(
        settings.start_url,
        mode=settings.mode,
        language=settings.language,
        robots_enabled=settings.respect_robots_txt,
        browser_type=settings.browser_type,
        headless=settings.headless,
    )

    snapshot = CrawlProgressSnapshot(
        site=site,
        output_dir=settings.output_dir.resolve(),
        state_dir=settings.state_dir.resolve(),
        max_requests=settings.max_requests,
        max_concurrency=settings.max_concurrency,
        requests_per_minute=settings.requests_per_minute,
        phase="Starting crawler",
    )

    return CrawlDashboard(
        snapshot,
        console=build_console(),
    )


def _apply_stats_to_dashboard(
    dashboard: CrawlDashboard,
    stats: CrawlStats,
) -> None:
    """Copy canonical crawl metrics into the dashboard snapshot."""

    dashboard.update(
        processed=stats.processed,
        saved=stats.saved,
        duplicate_content=stats.duplicate_content,
        incremental_skipped=stats.incremental_skipped,
        rejected_urls=stats.rejected_urls,
        empty_pages=stats.empty_pages,
        non_english=stats.non_english,
        failed=stats.failed,
        phase="Finalizing",
    )


def _apply_crawl_event(
    dashboard: CrawlDashboard,
    event: CrawlEvent,
) -> None:
    """Apply one crawler lifecycle event to the live dashboard."""

    snapshot_changes: dict[str, object] = {}

    for field_name in (
        "phase",
        "current_url",
        "current_title",
        "processed",
        "saved",
        "duplicate_content",
        "incremental_skipped",
        "rejected_urls",
        "empty_pages",
        "non_english",
        "failed",
        "queued",
        "discovered",
        "active_requests",
    ):
        value = getattr(
            event,
            field_name,
        )

        if value is not None:
            snapshot_changes[field_name] = value

    if snapshot_changes:
        dashboard.update(
            **snapshot_changes,
        )

    site_changes: dict[str, object] = {}

    if event.site_title:
        site_changes["title"] = event.site_title

    for event_field, site_field in (
        (
            "sitemap_urls",
            "sitemap_urls",
        ),
        (
            "sitemap_files_checked",
            "sitemap_files_checked",
        ),
        (
            "sitemap_files_found",
            "sitemap_files_found",
        ),
        (
            "sitemap_errors",
            "sitemap_errors",
        ),
    ):
        value = getattr(
            event,
            event_field,
        )

        if value is not None:
            site_changes[site_field] = value

    if site_changes:
        dashboard.update_site(
            **site_changes,
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Run the docsync CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)

    _apply_environment_overrides(args)
    settings = Settings.from_environment()

    if args.inventory_only:
        report = asyncio.run(
            run_inventory(
                start_url=settings.start_url,
                state_dir=settings.state_dir,
                max_requests=settings.max_requests,
                max_concurrency=settings.max_concurrency,
                requests_per_minute=settings.requests_per_minute,
                request_timeout_seconds=settings.request_timeout_seconds,
                language=settings.language,
                respect_robots_txt=settings.respect_robots_txt,
            )
        )

        print(report.render())
        print(f"Inventory report: {settings.state_dir / 'site-inventory.json'}")

        return 0 if report.discovery_complete else 2

    dashboard = _build_dashboard(settings)
    args._docsync_event_sink = lambda event: _apply_crawl_event(dashboard, event)
    dashboard.start()

    try:
        result = _invoke_run_crawler(args)
    except KeyboardInterrupt:
        dashboard.finish(interrupted=True)
        raise
    except BaseException:
        dashboard.update(
            failed=dashboard.snapshot.failed + 1,
            phase="Failed",
        )
        dashboard.finish()
        raise

    if inspect.isawaitable(result):
        result = asyncio.run(_await_crawler_result(result))

    if isinstance(result, CrawlStats):
        _apply_stats_to_dashboard(
            dashboard,
            result,
        )
        dashboard.update(
            active_requests=0,
            queued=0,
            phase="Finalizing",
        )
        dashboard.finish()

        # Preserve the canonical machine-readable compatibility summary.
        print(result.finished_summary())
        return int(result.exit_code)

    dashboard.update(
        active_requests=0,
        queued=0,
        phase="Finalizing",
    )
    dashboard.finish()
    return 0
