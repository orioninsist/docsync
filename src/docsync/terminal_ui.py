"""Professional Rich terminal dashboard for docsync crawl sessions."""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from time import monotonic
from typing import Any, Final, TextIO
from urllib.parse import urlsplit

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    ProgressColumn,
    Task,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from rich.text import Text

DOCSYNC_TITLE: Final[str] = "DOCSYNC"
UNKNOWN_VALUE: Final[str] = "—"


@dataclass(frozen=True, slots=True)
class SiteInformation:
    """Stable site metadata displayed by the terminal dashboard."""

    start_url: str
    domain: str
    scope_path: str
    title: str = ""
    mode: str = "http"
    language: str = "en"
    robots_enabled: bool = True
    sitemap_urls: int = 0
    sitemap_files_checked: int = 0
    sitemap_files_found: int = 0
    sitemap_errors: int = 0
    browser_type: str = ""
    headless: bool = True

    @classmethod
    def from_start_url(
        cls,
        start_url: str,
        *,
        mode: str,
        language: str,
        robots_enabled: bool,
        browser_type: str = "",
        headless: bool = True,
    ) -> SiteInformation:
        """Build initial display metadata from a normalized start URL."""

        parsed = urlsplit(start_url)
        scope_path = parsed.path or "/"

        return cls(
            start_url=start_url,
            domain=parsed.netloc or UNKNOWN_VALUE,
            scope_path=scope_path,
            mode=mode,
            language=language,
            robots_enabled=robots_enabled,
            browser_type=browser_type,
            headless=headless,
        )


@dataclass(frozen=True, slots=True)
class CrawlProgressSnapshot:
    """One immutable real-time crawl dashboard state."""

    site: SiteInformation
    output_dir: Path
    state_dir: Path
    max_requests: int
    max_concurrency: int
    requests_per_minute: int
    processed: int = 0
    saved: int = 0
    duplicate_content: int = 0
    incremental_skipped: int = 0
    rejected_urls: int = 0
    empty_pages: int = 0
    non_english: int = 0
    failed: int = 0
    queued: int = 0
    discovered: int = 0
    active_requests: int = 0
    current_url: str = ""
    current_title: str = ""
    phase: str = "Initializing"
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    elapsed_seconds: float = 0.0
    finished: bool = False
    interrupted: bool = False

    @property
    def completed_requests(self) -> int:
        """Return all terminal request outcomes represented by the snapshot."""

        return (
            self.saved
            + self.duplicate_content
            + self.incremental_skipped
            + self.rejected_urls
            + self.empty_pages
            + self.non_english
            + self.failed
        )

    @property
    def progress_total(self) -> int:
        """Return the best bounded progress total available."""

        discovered_total = max(
            self.discovered,
            self.processed + self.queued,
        )

        if discovered_total > 0:
            return min(
                max(discovered_total, self.processed),
                self.max_requests,
            )

        return self.max_requests

    @property
    def progress_completed(self) -> int:
        """Return progress completed without exceeding the displayed total."""

        return min(
            self.processed,
            self.progress_total,
        )

    @property
    def average_requests_per_minute(self) -> float:
        """Return observed average request throughput."""

        if self.elapsed_seconds <= 0:
            return 0.0

        return self.processed / self.elapsed_seconds * 60.0


class _PercentageColumn(ProgressColumn):
    """Render deterministic percentage text for the Rich progress bar."""

    def render(self, task: Task) -> Text:
        if task.total is None or task.total <= 0:
            return Text("  0.0%", style="progress.percentage")

        percentage = min(
            100.0,
            max(
                0.0,
                task.completed / task.total * 100.0,
            ),
        )
        return Text(
            f"{percentage:5.1f}%",
            style="progress.percentage",
        )


class DashboardRenderer:
    """Build Rich renderables without owning terminal lifecycle."""

    def render(
        self,
        snapshot: CrawlProgressSnapshot,
    ) -> RenderableType:
        """Render either the live dashboard or final completion report."""

        if snapshot.finished:
            return self.render_completion(snapshot)

        return self._render_plain_dashboard(snapshot)

    def _render_plain_dashboard(
        self,
        snapshot: CrawlProgressSnapshot,
    ) -> Text:
        """Render live fixed terminal dashboard."""

        terminal_outcomes = max(
            snapshot.completed_requests,
            snapshot.processed,
            1,
        )

        successful_outcomes = (
            snapshot.saved + snapshot.duplicate_content + snapshot.incremental_skipped
        )

        success_rate = min(
            100.0,
            successful_outcomes / terminal_outcomes * 100.0,
        )

        lines = [
            "DOCSYNC",
            "",
            "Crawl summary",
            f"Processed: {snapshot.processed}",
            f"Saved: {snapshot.saved}",
            f"Skipped total: {
                (
                    snapshot.duplicate_content
                    + snapshot.incremental_skipped
                    + snapshot.rejected_urls
                    + snapshot.empty_pages
                    + snapshot.non_english
                )
            }",
            f"Failed: {snapshot.failed}",
            f"Success rate: {success_rate:.1f}%",
            f"Elapsed: {_format_duration(snapshot.elapsed_seconds)}",
            f"Average speed: {snapshot.average_requests_per_minute:.1f} requests/min",
            f"Configured RPM: {snapshot.requests_per_minute}",
            f"Concurrency: {snapshot.max_concurrency} workers",
            "",
            "Current activity",
            f"Phase: {snapshot.phase}",
            f"URL: {snapshot.current_url or '-'}",
            f"Title: {snapshot.current_title or '-'}",
            "",
            "Site information",
            f"Target: {snapshot.site.start_url}",
            f"Domain: {snapshot.site.domain}",
            f"Language: {snapshot.site.language}",
            f"Mode: {snapshot.site.mode}",
            f"Browser: {snapshot.site.browser_type}",
            f"Headless: {_boolean_mark(snapshot.site.headless)}",
            f"Sitemap URLs: {snapshot.site.sitemap_urls}",
            (
                f"Sitemaps: {snapshot.site.sitemap_files_found} found / "
                f"{snapshot.site.sitemap_files_checked} checked / "
                f"{snapshot.site.sitemap_errors} errors"
            ),
            "",
            "Discovery",
            f"Discovered: {snapshot.discovered}",
            "",
            "Counters",
            f"Duplicate content: {snapshot.duplicate_content}",
            f"Incremental skipped: {snapshot.incremental_skipped}",
            f"Non English: {snapshot.non_english}",
            f"Rejected URLs: {snapshot.rejected_urls}",
            f"Empty pages: {snapshot.empty_pages}",
            "",
            "Storage",
            f"Output: {snapshot.output_dir}",
            f"State: {snapshot.state_dir}",
        ]

        return Text("\n".join(lines))

    def render_completion(
        self,
        snapshot: CrawlProgressSnapshot,
    ) -> RenderableType:
        """Render a detailed and stable completion report."""

        status_text, _border_style = self._completion_status(snapshot)

        skipped_total = (
            snapshot.duplicate_content
            + snapshot.incremental_skipped
            + snapshot.rejected_urls
            + snapshot.empty_pages
            + snapshot.non_english
        )

        successful_outcomes = (
            snapshot.saved + snapshot.duplicate_content + snapshot.incremental_skipped
        )

        terminal_outcomes = max(
            snapshot.completed_requests,
            snapshot.processed,
            1,
        )

        success_rate = min(
            100.0,
            successful_outcomes / terminal_outcomes * 100.0,
        )

        crawl_summary = Table.grid(
            padding=(0, 2),
        )
        crawl_summary.add_column(style="bold")
        crawl_summary.add_column(justify="right")
        crawl_summary.add_column(style="dim")

        crawl_summary.add_row(
            "Processed",
            str(snapshot.processed),
            "requests",
        )
        crawl_summary.add_row(
            "Saved",
            str(snapshot.saved),
            "Markdown files",
        )
        crawl_summary.add_row(
            "Skipped total",
            str(skipped_total),
            "pages",
        )
        crawl_summary.add_row(
            "Duplicate",
            str(snapshot.duplicate_content),
            "content matches",
        )
        crawl_summary.add_row(
            "Incremental skipped",
            str(snapshot.incremental_skipped),
            "fresh URLs",
        )
        crawl_summary.add_row(
            "Rejected",
            str(snapshot.rejected_urls),
            "URLs",
        )
        crawl_summary.add_row(
            "Empty",
            str(snapshot.empty_pages),
            "pages",
        )
        crawl_summary.add_row(
            "Non-English",
            str(snapshot.non_english),
            "pages",
        )
        crawl_summary.add_row(
            "Failed",
            str(snapshot.failed),
            "requests",
        )
        crawl_summary.add_section()
        crawl_summary.add_row(
            "Success rate",
            f"{success_rate:.1f}%",
            "",
        )
        crawl_summary.add_row(
            "Elapsed",
            _format_duration(snapshot.elapsed_seconds),
            "",
        )
        crawl_summary.add_row(
            "Average speed",
            f"{snapshot.average_requests_per_minute:.1f}",
            "requests/min",
        )
        crawl_summary.add_row(
            "Configured RPM",
            str(snapshot.requests_per_minute),
            "requests/min",
        )
        crawl_summary.add_row(
            "Concurrency",
            str(snapshot.max_concurrency),
            "workers",
        )

        site_summary = Table.grid(
            padding=(0, 2),
        )
        site_summary.add_column(style="bold")
        site_summary.add_column(overflow="fold")

        site_summary.add_row(
            "Target",
            snapshot.site.start_url,
        )
        site_summary.add_row(
            "Domain",
            snapshot.site.domain,
        )
        site_summary.add_row(
            "Scope",
            snapshot.site.scope_path,
        )
        site_summary.add_row(
            "Title",
            snapshot.site.title or UNKNOWN_VALUE,
        )
        site_summary.add_row(
            "Mode",
            snapshot.site.mode,
        )
        site_summary.add_row(
            "Language",
            snapshot.site.language,
        )
        site_summary.add_row(
            "robots.txt",
            _boolean_mark(snapshot.site.robots_enabled),
        )
        site_summary.add_row(
            "Sitemap URLs",
            str(snapshot.site.sitemap_urls),
        )
        site_summary.add_row(
            "Sitemaps",
            (
                f"{snapshot.site.sitemap_files_found} found / "
                f"{snapshot.site.sitemap_files_checked} checked / "
                f"{snapshot.site.sitemap_errors} errors"
            ),
        )

        if snapshot.site.mode == "playwright":
            site_summary.add_row(
                "Browser",
                snapshot.site.browser_type or UNKNOWN_VALUE,
            )
            site_summary.add_row(
                "Headless",
                _boolean_mark(snapshot.site.headless),
            )

        storage_summary = Table.grid(
            padding=(0, 2),
        )
        storage_summary.add_column(style="bold")
        storage_summary.add_column(overflow="fold")

        storage_summary.add_row(
            "Output",
            str(snapshot.output_dir),
        )
        storage_summary.add_row(
            "State",
            str(snapshot.state_dir),
        )
        storage_summary.add_row(
            "Request limit",
            str(snapshot.max_requests),
        )
        storage_summary.add_row(
            "Discovered",
            str(snapshot.discovered),
        )

        return Group(
            Text("DOCSYNC"),
            Text(""),
            Text(status_text),
            Text(""),
            Text("Crawl summary"),
            Text(f"Processed: {snapshot.processed}"),
            Text(f"Saved: {snapshot.saved}"),
            Text(f"Skipped total: {skipped_total}"),
            Text(f"Failed: {snapshot.failed}"),
            Text(f"Success rate: {success_rate:.1f}%"),
            Text(f"Elapsed: {_format_duration(snapshot.elapsed_seconds)}"),
            Text(
                f"Average speed: {snapshot.average_requests_per_minute:.1f} requests/min"
            ),
            Text(f"Configured RPM: {snapshot.requests_per_minute}"),
            Text(f"Concurrency: {snapshot.max_concurrency} workers"),
            Text(""),
            Text("Site information"),
            Text(f"Target: {snapshot.site.start_url}"),
            Text(f"Domain: {snapshot.site.domain}"),
            Text(f"Title: {snapshot.site.title}"),
            Text(f"Language: {snapshot.site.language}"),
            Text(f"Sitemap URLs: {snapshot.site.sitemap_urls}"),
            Text(
                f"Sitemaps: {snapshot.site.sitemap_files_found} found / "
                f"{snapshot.site.sitemap_files_checked} checked / "
                f"{snapshot.site.sitemap_errors} errors"
            ),
            Text(f"Mode: {snapshot.site.mode}"),
            Text(f"Browser: {snapshot.site.browser_type or 'unknown'}"),
            Text(f"Headless: {_boolean_mark(snapshot.site.headless)}"),
            Text(""),
            Text("Output and state"),
            Text(f"Output: {snapshot.output_dir}"),
            Text(f"State: {snapshot.state_dir}"),
            Text(f"Discovered: {snapshot.discovered}"),
        )

    @staticmethod
    def _render_header(
        snapshot: CrawlProgressSnapshot,
    ) -> Panel:
        mode = snapshot.site.mode.upper()
        phase = snapshot.phase

        subtitle = Text()
        subtitle.append(mode, style="bold cyan")
        subtitle.append("  •  ", style="dim")
        subtitle.append(phase, style="bold")

        return Panel(
            subtitle,
            title=f"[bold]{DOCSYNC_TITLE}[/bold]",
            border_style="cyan",
            padding=(0, 2),
        )

    @staticmethod
    def _render_site_table(
        snapshot: CrawlProgressSnapshot,
    ) -> Panel:
        site = snapshot.site

        table = Table.grid(
            padding=(0, 2),
        )
        table.add_column(style="bold")
        table.add_column(overflow="fold")

        table.add_row("URL", site.start_url)
        table.add_row("Domain", site.domain)
        table.add_row("Scope", site.scope_path)
        table.add_row("Title", site.title or UNKNOWN_VALUE)
        table.add_row("Language", site.language)
        table.add_row("Mode", site.mode)
        table.add_row("robots.txt", _boolean_mark(site.robots_enabled))
        table.add_row(
            "Sitemaps",
            (
                f"{site.sitemap_files_found} found / "
                f"{site.sitemap_files_checked} checked / "
                f"{site.sitemap_errors} errors"
            ),
        )
        table.add_row("Sitemap URLs", str(site.sitemap_urls))

        if site.mode == "playwright":
            table.add_row(
                "Browser",
                site.browser_type or UNKNOWN_VALUE,
            )
            table.add_row(
                "Headless",
                _boolean_mark(site.headless),
            )

        return Panel(
            table,
            title="[bold]Target[/bold]",
            border_style="blue",
            padding=(0, 1),
        )

    @staticmethod
    def _render_progress(
        snapshot: CrawlProgressSnapshot,
    ) -> Panel:
        progress = Progress(
            TextColumn("[bold]{task.description}"),
            BarColumn(
                bar_width=None,
                complete_style="green",
                finished_style="green",
                pulse_style="cyan",
            ),
            _PercentageColumn(),
            TextColumn("[dim]{task.completed:.0f}/{task.total:.0f}[/dim]"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            expand=True,
        )

        progress.add_task(
            "Crawl",
            total=max(
                snapshot.progress_total,
                1,
            ),
            completed=snapshot.progress_completed,
        )

        return Panel(
            progress,
            title="[bold]Progress[/bold]",
            border_style="green",
            padding=(0, 1),
        )

    @staticmethod
    def _render_statistics(
        snapshot: CrawlProgressSnapshot,
    ) -> Panel:
        table = Table(
            show_header=True,
            header_style="bold",
            expand=True,
            box=None,
            pad_edge=False,
        )
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_column("Metric")
        table.add_column("Value", justify="right")

        table.add_row(
            "Processed",
            str(snapshot.processed),
            "Queued",
            str(snapshot.queued),
        )
        table.add_row(
            "Discovered",
            str(snapshot.discovered),
            "Active",
            str(snapshot.active_requests),
        )
        table.add_row(
            "Saved",
            str(snapshot.saved),
            "Duplicate",
            str(snapshot.duplicate_content),
        )
        table.add_row(
            "Incremental",
            str(snapshot.incremental_skipped),
            "Rejected",
            str(snapshot.rejected_urls),
        )
        table.add_row(
            "Empty",
            str(snapshot.empty_pages),
            "Non-English",
            str(snapshot.non_english),
        )
        table.add_row(
            "Failed",
            str(snapshot.failed),
            "Observed RPM",
            f"{snapshot.average_requests_per_minute:.1f}",
        )
        table.add_row(
            "RPM limit",
            str(snapshot.requests_per_minute),
            "Concurrency",
            (f"{snapshot.active_requests}/{snapshot.max_concurrency}"),
        )

        return Panel(
            table,
            title="[bold]Statistics[/bold]",
            border_style="magenta",
            padding=(0, 1),
        )

    @staticmethod
    def _render_current_activity(
        snapshot: CrawlProgressSnapshot,
    ) -> Panel:
        table = Table.grid(
            padding=(0, 2),
        )
        table.add_column(style="bold")
        table.add_column(overflow="fold")

        table.add_row(
            "URL",
            snapshot.current_url or UNKNOWN_VALUE,
        )
        table.add_row(
            "Title",
            snapshot.current_title or UNKNOWN_VALUE,
        )
        table.add_row(
            "Elapsed",
            _format_duration(snapshot.elapsed_seconds),
        )

        return Panel(
            table,
            title="[bold]Current activity[/bold]",
            border_style="yellow",
            padding=(0, 1),
        )

    @staticmethod
    def _render_paths(
        snapshot: CrawlProgressSnapshot,
    ) -> Panel:
        table = Table.grid(
            padding=(0, 2),
        )
        table.add_column(style="bold")
        table.add_column(overflow="fold")

        table.add_row("Output", str(snapshot.output_dir))
        table.add_row("State", str(snapshot.state_dir))

        return Panel(
            table,
            title="[bold]Storage[/bold]",
            border_style="dim",
            padding=(0, 1),
        )

    @staticmethod
    def _completion_status(
        snapshot: CrawlProgressSnapshot,
    ) -> tuple[str, str]:
        if snapshot.interrupted:
            return "Interrupted", "yellow"

        if snapshot.failed > 0:
            return "Completed with failures", "red"

        return "Completed successfully", "green"


class CrawlDashboard:
    """Thread-safe Rich Live dashboard lifecycle and state owner."""

    def __init__(
        self,
        snapshot: CrawlProgressSnapshot,
        *,
        console: Console | None = None,
        enabled: bool | None = None,
        refresh_per_second: float = 8.0,
    ) -> None:
        if refresh_per_second <= 0:
            raise ValueError("refresh_per_second must be greater than zero")

        self._console = console or Console()
        self._enabled = self._console.is_terminal if enabled is None else enabled
        self._renderer = DashboardRenderer()
        self._snapshot = snapshot
        self._started_monotonic = monotonic()
        self._live: Live | None = None
        self._refresh_per_second = refresh_per_second
        self._lock = threading.RLock()

    @property
    def snapshot(self) -> CrawlProgressSnapshot:
        """Return the current immutable snapshot."""

        with self._lock:
            return self._snapshot

    @property
    def enabled(self) -> bool:
        """Return whether interactive rendering is enabled."""

        return self._enabled

    def start(self) -> None:
        """Start the interactive Live terminal dashboard."""

        with self._lock:
            if not self._enabled or self._live is not None:
                return

            self._live = Live(
                self._renderer.render(self._with_elapsed(self._snapshot)),
                console=self._console,
                refresh_per_second=self._refresh_per_second,
                transient=False,
                screen=False,
                vertical_overflow="crop",
            )
            self._live.start(refresh=True)

    def update(
        self,
        **changes: Any,
    ) -> CrawlProgressSnapshot:
        """Atomically replace selected snapshot fields and refresh the dashboard."""

        with self._lock:
            updated = replace(
                self._snapshot,
                **changes,
            )
            updated = self._with_elapsed(updated)
            self._snapshot = updated
            self._refresh_locked()
            return updated

    def update_site(
        self,
        **changes: Any,
    ) -> CrawlProgressSnapshot:
        """Atomically update site metadata and refresh the dashboard."""

        with self._lock:
            updated_site = replace(
                self._snapshot.site,
                **changes,
            )
            self._snapshot = self._with_elapsed(
                replace(
                    self._snapshot,
                    site=updated_site,
                )
            )
            self._refresh_locked()
            return self._snapshot

    def finish(
        self,
        *,
        interrupted: bool = False,
    ) -> CrawlProgressSnapshot:
        """Stop Live rendering and print the final completion summary."""

        with self._lock:
            self._snapshot = self._with_elapsed(
                replace(
                    self._snapshot,
                    finished=True,
                    interrupted=interrupted,
                    active_requests=0,
                    phase=("Interrupted" if interrupted else "Finished"),
                )
            )

            if self._live is not None:
                self._live.update(
                    self._renderer.render_completion(self._snapshot),
                    refresh=True,
                )
                self._live.stop()
                self._live = None
            elif self._enabled:
                self._console.print(self._renderer.render_completion(self._snapshot))

            return self._snapshot

    def render_text(
        self,
        *,
        width: int = 120,
    ) -> str:
        """Render the current dashboard as plain text for tests and logs."""

        with self._lock:
            buffer = StringIO()
            console = Console(
                file=buffer,
                width=width,
                force_terminal=False,
                color_system=None,
                legacy_windows=False,
            )
            console.print(self._renderer.render(self._with_elapsed(self._snapshot)))
            return buffer.getvalue()

    def _with_elapsed(
        self,
        snapshot: CrawlProgressSnapshot,
    ) -> CrawlProgressSnapshot:
        elapsed_seconds = max(
            snapshot.elapsed_seconds,
            monotonic() - self._started_monotonic,
        )
        return replace(
            snapshot,
            elapsed_seconds=elapsed_seconds,
        )

    def _refresh_locked(self) -> None:
        if self._live is None:
            return

        self._live.update(
            self._renderer.render(self._snapshot),
            refresh=True,
        )


def build_console(
    *,
    stream: TextIO | None = None,
    force_terminal: bool | None = None,
) -> Console:
    """Create the canonical docsync Rich console."""

    resolved_stream = stream or sys.stdout

    return Console(
        file=resolved_stream,
        force_terminal=force_terminal,
        highlight=False,
        soft_wrap=False,
    )


def _boolean_mark(value: bool) -> str:
    return "✓ enabled" if value else "✗ disabled"


def _format_duration(seconds: float) -> str:
    bounded_seconds = max(
        0,
        int(seconds),
    )
    hours, remainder = divmod(
        bounded_seconds,
        3600,
    )
    minutes, remaining_seconds = divmod(
        remainder,
        60,
    )

    return f"{hours:02d}:{minutes:02d}:{remaining_seconds:02d}"
