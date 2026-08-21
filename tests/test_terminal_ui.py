"""Behavioral tests for the professional Rich terminal dashboard."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from rich.console import Console

from docsync.terminal_ui import (
    CrawlDashboard,
    CrawlProgressSnapshot,
    DashboardRenderer,
    SiteInformation,
    build_console,
)


def build_snapshot(
    tmp_path: Path,
    **changes: object,
) -> CrawlProgressSnapshot:
    site = SiteInformation.from_start_url(
        "https://github.com/tmux/tmux/wiki",
        mode="http",
        language="en",
        robots_enabled=True,
    )

    defaults: dict[str, object] = {
        "site": site,
        "output_dir": tmp_path / "markdown",
        "state_dir": tmp_path / "state",
        "max_requests": 20,
        "max_concurrency": 2,
        "requests_per_minute": 20,
    }
    defaults.update(changes)

    return CrawlProgressSnapshot(**defaults)


def test_site_information_is_derived_from_start_url() -> None:
    site = SiteInformation.from_start_url(
        "https://github.com/tmux/tmux/wiki",
        mode="playwright",
        language="en",
        robots_enabled=True,
        browser_type="chromium",
        headless=True,
    )

    assert site.domain == "github.com"
    assert site.scope_path == "/tmux/tmux/wiki"
    assert site.mode == "playwright"
    assert site.browser_type == "chromium"
    assert site.robots_enabled is True


def test_progress_snapshot_uses_discovered_total(
    tmp_path: Path,
) -> None:
    snapshot = build_snapshot(
        tmp_path,
        processed=7,
        queued=5,
        discovered=12,
    )

    assert snapshot.progress_total == 12
    assert snapshot.progress_completed == 7


def test_progress_snapshot_is_bounded_by_request_limit(
    tmp_path: Path,
) -> None:
    snapshot = build_snapshot(
        tmp_path,
        processed=20,
        queued=50,
        discovered=70,
    )

    assert snapshot.progress_total == 20
    assert snapshot.progress_completed == 20


def test_average_requests_per_minute(
    tmp_path: Path,
) -> None:
    snapshot = build_snapshot(
        tmp_path,
        processed=10,
        elapsed_seconds=30.0,
    )

    assert snapshot.average_requests_per_minute == pytest.approx(20.0)


def test_dashboard_plain_text_contains_core_sections(
    tmp_path: Path,
) -> None:
    dashboard = CrawlDashboard(
        build_snapshot(
            tmp_path,
            processed=8,
            saved=6,
            queued=4,
            discovered=12,
            current_url="https://github.com/tmux/tmux/wiki/Getting-Started",
            current_title="Getting Started",
            phase="Crawling",
        ),
        enabled=False,
    )

    rendered = dashboard.render_text()

    assert "DOCSYNC" in rendered
    assert "Target" in rendered
    assert "Crawl summary" in rendered
    assert "Average speed" in rendered
    assert "Current activity" in rendered
    assert "Storage" in rendered
    assert "github.com" in rendered
    assert "Getting Started" in rendered
    assert "Processed" in rendered
    assert "Saved" in rendered


def test_dashboard_update_preserves_immutable_snapshots(
    tmp_path: Path,
) -> None:
    initial = build_snapshot(tmp_path)
    dashboard = CrawlDashboard(
        initial,
        enabled=False,
    )

    updated = dashboard.update(
        processed=1,
        saved=1,
        current_url="https://github.com/tmux/tmux/wiki",
        phase="Crawling",
    )

    assert initial.processed == 0
    assert updated.processed == 1
    assert updated.saved == 1
    assert updated.phase == "Crawling"


def test_dashboard_site_update(
    tmp_path: Path,
) -> None:
    dashboard = CrawlDashboard(
        build_snapshot(tmp_path),
        enabled=False,
    )

    updated = dashboard.update_site(
        title="tmux Wiki",
        sitemap_urls=17,
        sitemap_files_checked=3,
        sitemap_files_found=1,
        sitemap_errors=2,
    )

    assert updated.site.title == "tmux Wiki"
    assert updated.site.sitemap_urls == 17
    assert updated.site.sitemap_files_checked == 3
    assert updated.site.sitemap_files_found == 1
    assert updated.site.sitemap_errors == 2


def test_completion_report_contains_release_summary(
    tmp_path: Path,
) -> None:
    dashboard = CrawlDashboard(
        build_snapshot(
            tmp_path,
            processed=20,
            saved=17,
            duplicate_content=1,
            incremental_skipped=1,
            failed=1,
            elapsed_seconds=60.0,
        ),
        enabled=False,
    )

    dashboard.finish()
    rendered = dashboard.render_text()

    assert "Completed with failures" in rendered
    assert "Processed" in rendered
    assert "20" in rendered
    assert "Saved" in rendered
    assert "17" in rendered
    assert "Average speed" in rendered
    assert "Output" in rendered
    assert "State" in rendered


def test_successful_completion_status(
    tmp_path: Path,
) -> None:
    snapshot = build_snapshot(
        tmp_path,
        finished=True,
        processed=2,
        saved=2,
    )

    console = Console(
        width=100,
        force_terminal=False,
        color_system=None,
        record=True,
    )
    console.print(DashboardRenderer().render_completion(snapshot))
    rendered = console.export_text()

    assert "Completed successfully" in rendered


def test_interrupted_completion_status(
    tmp_path: Path,
) -> None:
    snapshot = build_snapshot(
        tmp_path,
        finished=True,
        interrupted=True,
    )

    console = Console(
        width=100,
        force_terminal=False,
        color_system=None,
        record=True,
    )
    console.print(DashboardRenderer().render_completion(snapshot))
    rendered = console.export_text()

    assert "Interrupted" in rendered


def test_build_console_targets_supplied_stream() -> None:
    from io import StringIO

    stream = StringIO()
    console = build_console(
        stream=stream,
        force_terminal=False,
    )

    console.print("docsync")

    assert "docsync" in stream.getvalue()


def test_noninteractive_dashboard_does_not_render_live_output(
    tmp_path: Path,
) -> None:
    from io import StringIO

    stream = StringIO()
    console = Console(
        file=stream,
        force_terminal=False,
        color_system=None,
    )
    dashboard = CrawlDashboard(
        build_snapshot(
            tmp_path,
            processed=1,
            saved=1,
        ),
        console=console,
    )

    assert dashboard.enabled is False

    dashboard.start()
    dashboard.update(
        phase="Crawling",
        active_requests=1,
        queued=2,
    )
    dashboard.finish()

    assert stream.getvalue() == ""


def test_explicitly_disabled_dashboard_is_silent(
    tmp_path: Path,
) -> None:
    from io import StringIO

    stream = StringIO()
    console = Console(
        file=stream,
        force_terminal=True,
    )
    dashboard = CrawlDashboard(
        build_snapshot(tmp_path),
        console=console,
        enabled=False,
    )

    dashboard.start()
    dashboard.update(
        phase="Crawling",
        processed=1,
    )
    dashboard.finish()

    assert stream.getvalue() == ""


def test_noninteractive_dashboard_still_tracks_state(
    tmp_path: Path,
) -> None:
    from io import StringIO

    dashboard = CrawlDashboard(
        build_snapshot(tmp_path),
        console=Console(
            file=StringIO(),
            force_terminal=False,
            color_system=None,
        ),
    )

    updated = dashboard.update(
        phase="Downloading",
        processed=3,
        active_requests=2,
        current_url="https://example.com/docs/page",
    )
    finished = dashboard.finish()

    assert dashboard.enabled is False
    assert updated.processed == 3
    assert updated.active_requests == 2
    assert finished.finished is True
    assert finished.active_requests == 0


def test_richer_completion_report_contains_site_and_performance_details(
    tmp_path: Path,
) -> None:
    site = SiteInformation.from_start_url(
        "https://example.com/docs",
        mode="playwright",
        language="en",
        robots_enabled=True,
        browser_type="chromium",
        headless=True,
    )
    site = replace(
        site,
        title="Example Documentation",
        sitemap_urls=12,
        sitemap_files_checked=3,
        sitemap_files_found=2,
        sitemap_errors=1,
    )

    snapshot = CrawlProgressSnapshot(
        site=site,
        output_dir=tmp_path / "markdown",
        state_dir=tmp_path / "state",
        max_requests=25,
        max_concurrency=3,
        requests_per_minute=18,
        processed=10,
        saved=6,
        duplicate_content=1,
        incremental_skipped=1,
        rejected_urls=1,
        empty_pages=0,
        non_english=0,
        failed=1,
        discovered=14,
        elapsed_seconds=30.0,
        finished=True,
        phase="Finished",
    )

    console = Console(
        width=120,
        force_terminal=False,
        color_system=None,
        record=True,
    )
    console.print(DashboardRenderer().render_completion(snapshot))
    rendered = console.export_text()

    assert "Crawl summary" in rendered
    assert "Site information" in rendered
    assert "Output and state" in rendered
    assert "Skipped total" in rendered
    assert "Success rate" in rendered
    assert "Configured RPM" in rendered
    assert "Concurrency" in rendered
    assert "Example Documentation" in rendered
    assert "Sitemap URLs" in rendered
    assert "12" in rendered
    assert "2 found / 3 checked / 1 errors" in rendered
    assert "https://example.com/docs" in rendered
    assert "playwright" in rendered
    assert "Browser" in rendered
    assert "chromium" in rendered
    assert "Discovered" in rendered
    assert "14" in rendered


def test_richer_completion_success_rate_is_bounded(
    tmp_path: Path,
) -> None:
    snapshot = build_snapshot(
        tmp_path,
        processed=4,
        saved=2,
        duplicate_content=1,
        incremental_skipped=1,
        failed=0,
        elapsed_seconds=60.0,
        finished=True,
    )

    console = Console(
        width=100,
        force_terminal=False,
        color_system=None,
        record=True,
    )
    console.print(DashboardRenderer().render_completion(snapshot))
    rendered = console.export_text()

    assert "Success rate" in rendered
    assert "100.0%" in rendered


def test_richer_completion_report_preserves_failure_status(
    tmp_path: Path,
) -> None:
    snapshot = build_snapshot(
        tmp_path,
        processed=3,
        saved=2,
        failed=1,
        finished=True,
    )

    console = Console(
        width=100,
        force_terminal=False,
        color_system=None,
        record=True,
    )
    console.print(DashboardRenderer().render_completion(snapshot))
    rendered = console.export_text()

    assert "Completed with failures" in rendered
    assert "Failed" in rendered
    assert "1" in rendered
