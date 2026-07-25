"""Single terminal presentation boundary for the crawler runtime."""

from __future__ import annotations

import logging
import math
from collections.abc import Generator, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

from rich.console import Console, RenderableType
from rich.live import Live

from crawler.progress import RichDashboard


class TerminalUIHandle(Protocol):
    """Minimal live-display interface required by crawler orchestration."""

    def update(
        self,
        renderable: RenderableType,
        *,
        refresh: bool = False,
    ) -> None:
        """Replace the current renderable."""


class RunSummaryDashboard(Protocol):
    """Dashboard values needed by the final summary."""

    @property
    def processed(self) -> int:
        """Return the number of processed URLs."""
        ...

    @property
    def downloaded(self) -> int:
        """Return the number of downloaded URLs."""
        ...

    @property
    def skipped(self) -> int:
        """Return the number of skipped URLs."""
        ...

    @property
    def duplicates(self) -> int:
        """Return the number of duplicate URLs."""
        ...

    @property
    def errors(self) -> int:
        """Return the number of failed URLs."""
        ...


class RunSummaryQueueCounts(Protocol):
    """Queue values needed by the final summary."""

    @property
    def queued(self) -> int:
        """Return the total number of queued URLs."""
        ...

    @property
    def done(self) -> int:
        """Return the number of completed queue items."""
        ...

    @property
    def pending(self) -> int:
        """Return the number of pending queue items."""
        ...

    @property
    def processing(self) -> int:
        """Return the number of processing queue items."""
        ...

    @property
    def errors(self) -> int:
        """Return the number of failed queue items."""
        ...


class RunSummaryPaths(Protocol):
    """Filesystem paths needed by the final summary."""

    @property
    def output_dir(self) -> Path:
        """Return the crawler output directory."""
        ...

    @property
    def db_path(self) -> Path:
        """Return the crawler database path."""
        ...

    @property
    def log_file(self) -> Path:
        """Return the crawler log file path."""
        ...


class TerminalUI:
    """Own all crawler terminal presentation and Rich Live lifecycle."""

    def __init__(self, console: Console | None = None) -> None:
        self._console: Console = console or Console(force_terminal=True)

    @contextmanager
    def open(
        self,
        dashboard: RichDashboard,
        *,
        refresh_per_second: int,
    ) -> Generator[TerminalUIHandle]:
        """Open one persistent Rich Live display for a crawl operation."""

        with self._suspend_console_logging():
            with Live(
                dashboard.render(),
                console=self._console,
                refresh_per_second=refresh_per_second,
                transient=False,
                redirect_stdout=True,
                redirect_stderr=True,
            ) as live:
                yield live

    def show_preliminary_summary(
        self,
        *,
        sitemap_pages_found: int,
        seed_pages_queued: int,
        total_queued_urls: int,
        queue_status_counts: Mapping[str, int],
        interrupted_items_restored: int,
        missing_markdown_outputs_restored: int,
        recursive_discovery: bool,
        max_pages: int,
        auto_continue_until_complete: bool,
        max_auto_batches: str,
        batch_pause_seconds: float,
        max_queue_size: int,
        max_depth: int,
        allowed_path_prefix: str,
        min_delay: float,
        max_delay: float,
        robots_crawl_delay: object,
        proceed_message: str,
    ) -> None:
        """Render the complete preliminary crawler summary."""

        pending_count = queue_status_counts.get("pending", 0)
        estimated_batches = (
            math.ceil(pending_count / max(max_pages, 1)) if pending_count > 0 else 0
        )

        lines = [
            f"Sitemap pages found: {sitemap_pages_found}",
            f"Seed pages queued: {seed_pages_queued}",
            f"Total queued URLs: {total_queued_urls}",
            f"Queue pending: {pending_count}",
            f"Queue done: {queue_status_counts.get('done', 0)}",
            f"Queue error: {queue_status_counts.get('error', 0)}",
            f"Interrupted items restored to pending: {interrupted_items_restored}",
            (
                "Missing Markdown outputs restored to pending: "
                f"{missing_markdown_outputs_restored}"
            ),
            f"Recursive discovery: {recursive_discovery}",
            f"Max pages per batch: {max_pages}",
            f"Auto continue until complete: {auto_continue_until_complete}",
            f"Estimated batches: {estimated_batches}",
            f"Max auto batches: {max_auto_batches}",
            f"Pause between batches: {batch_pause_seconds}s",
            f"Max queue size: {max_queue_size}",
            f"Max depth: {max_depth}",
            f"Allowed path: {allowed_path_prefix}",
            f"Rate limit: {min_delay}s - {max_delay}s",
            f"Robots crawl-delay: {robots_crawl_delay}",
            proceed_message,
        ]

        self._show_section(
            title="Preliminary Summary",
            lines=lines,
        )

    def show_runtime_banner(self) -> None:
        """Render the runtime progress introduction."""

        self._show_section(
            title="Runtime Progress",
            lines=[
                "Single-table terminal progress is enabled.",
                "Crawler activity remains inside one persistent Rich Live dashboard.",
            ],
        )

    def show_final_run_summary(
        self,
        *,
        dashboard: RunSummaryDashboard,
        queue_counts: RunSummaryQueueCounts,
        paths: RunSummaryPaths,
        max_pages: int,
    ) -> None:
        """Render the final crawler run summary."""

        lines = [
            f"This command processed: {dashboard.processed}",
            f"This command downloaded/updated/restored: {dashboard.downloaded}",
            f"This command skipped: {dashboard.skipped}",
            f"This command duplicates: {dashboard.duplicates}",
            f"This command errors: {dashboard.errors}",
            f"Database queued total: {queue_counts.queued}",
            f"Database queue done: {queue_counts.done}",
            f"Database queue pending: {queue_counts.pending}",
            f"Database queue processing: {queue_counts.processing}",
            f"Database queue error: {queue_counts.errors}",
            f"Output directory: {paths.output_dir}",
            f"Database file: {paths.db_path}",
            f"Log file: {paths.log_file}",
            "",
        ]

        if queue_counts.pending > 0:
            remaining_runs = math.ceil(queue_counts.pending / max(max_pages, 1))
            lines.extend(
                [
                    "STATUS: INCOMPLETE - QUEUE STILL HAS PENDING URLS",
                    f"Approximate additional batch count: {remaining_runs}",
                    (
                        "If auto_continue_until_complete is true and this "
                        "message still appears, the stop reason is usually "
                        "max_auto_batches, max_queue_size, a crash, or no "
                        "processable pending item. Re-running the same command "
                        "continues from the database without duplicating "
                        "existing Markdown."
                    ),
                ]
            )
        elif queue_counts.errors > 0:
            lines.extend(
                [
                    "STATUS: FINISHED WITH ERRORS",
                    (
                        "No pending URL remains, but some URLs failed. "
                        "Check crawler.log for details. Re-running will not "
                        "duplicate existing Markdown."
                    ),
                ]
            )
        else:
            lines.extend(
                [
                    "STATUS: COMPLETE",
                    (
                        "No pending URL remains. The current crawl queue is "
                        "complete. Later re-runs update changed pages, restore "
                        "missing Markdown files, and skip duplicates by URL, "
                        "final URL, canonical URL, redirect target, and "
                        "content hash."
                    ),
                ]
            )

        self._show_section(
            title="Run Summary",
            lines=lines,
        )

    def show_observability_report(
        self,
        *,
        report_path: Path,
    ) -> None:
        """Render observability report locations."""

        self._show_section(
            title="Observability Report",
            lines=[
                f"Report: {report_path}",
                f"JSON: {report_path.with_suffix('.json')}",
            ],
        )

    def _show_section(
        self,
        *,
        title: str,
        lines: list[str],
    ) -> None:
        """Render a plain terminal section through the single UI boundary."""

        self._console.print()
        self._console.print(title)
        self._console.print("-" * len(title))

        for line in lines:
            self._console.print(line)

        self._console.print()

    @contextmanager
    def _suspend_console_logging(self) -> Generator[None]:
        """
        Temporarily detach terminal logging handlers.

        FileHandler instances remain active so crawler.log continues receiving
        the complete execution history while Rich Live owns the terminal.
        """

        suspended_handlers: list[tuple[logging.Logger, logging.Handler]] = []

        for logger in self._iter_loggers():
            for handler in tuple(logger.handlers):
                if not self._is_console_handler(handler):
                    continue

                logger.removeHandler(handler)
                suspended_handlers.append((logger, handler))

        try:
            yield
        finally:
            for logger, handler in suspended_handlers:
                logger.addHandler(handler)

    @staticmethod
    def _is_console_handler(handler: logging.Handler) -> bool:
        return isinstance(handler, logging.StreamHandler) and not isinstance(
            handler,
            logging.FileHandler,
        )

    @staticmethod
    def _iter_loggers() -> Iterator[logging.Logger]:
        yield logging.getLogger()

        for logger_object in logging.Logger.manager.loggerDict.values():
            if isinstance(logger_object, logging.Logger):
                yield logger_object


__all__ = [
    "TerminalUI",
    "TerminalUIHandle",
]
