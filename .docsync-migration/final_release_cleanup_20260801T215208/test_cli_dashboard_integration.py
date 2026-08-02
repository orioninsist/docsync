"""Canonical CLI integration tests for the Rich crawl dashboard."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, ClassVar

import pytest

from docsync.cli import main
from docsync.metrics import CrawlStats
from docsync.terminal_ui import CrawlProgressSnapshot, SiteInformation


class FakeDashboard:
    """Small dashboard spy used by CLI integration tests."""

    instances: ClassVar[list[FakeDashboard]] = []

    def __init__(
        self,
        snapshot: CrawlProgressSnapshot,
        **_: Any,
    ) -> None:
        self._snapshot = snapshot
        self.started = False
        self.finished = False
        self.interrupted = False
        self.updates: list[dict[str, object]] = []
        type(self).instances.append(self)

    @property
    def snapshot(self) -> CrawlProgressSnapshot:
        return self._snapshot

    def start(self) -> None:
        self.started = True

    def update(
        self,
        **changes: object,
    ) -> CrawlProgressSnapshot:
        self.updates.append(changes)
        self._snapshot = replace(
            self._snapshot,
            **changes,
        )
        return self._snapshot

    def update_site(
        self,
        **changes: Any,
    ) -> CrawlProgressSnapshot:
        self._snapshot = replace(
            self._snapshot,
            site=replace(
                self._snapshot.site,
                **changes,
            ),
        )
        return self._snapshot

    def finish(
        self,
        *,
        interrupted: bool = False,
    ) -> CrawlProgressSnapshot:
        self.finished = True
        self.interrupted = interrupted
        self._snapshot = replace(
            self._snapshot,
            finished=True,
            interrupted=interrupted,
        )
        return self._snapshot


@pytest.fixture(autouse=True)
def clear_dashboard_instances() -> None:
    FakeDashboard.instances.clear()


def configure_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "DOCSYNC_OUTPUT_DIR",
        str(tmp_path / "output"),
    )
    monkeypatch.setenv(
        "DOCSYNC_STATE_DIR",
        str(tmp_path / "state"),
    )
    monkeypatch.setenv(
        "DOCSYNC_LOG_DIR",
        str(tmp_path / "logs"),
    )


def test_cli_starts_updates_and_finishes_dashboard(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_runtime(
        monkeypatch,
        tmp_path,
    )

    stats = CrawlStats(
        mode="http",
        processed=8,
        saved=5,
        duplicate_content=1,
        incremental_skipped=1,
        rejected_urls=2,
        empty_pages=3,
        non_english=4,
        failed=0,
    )

    async def fake_run_crawler(
        start_url: str,
        **_: Any,
    ) -> CrawlStats:
        assert start_url == "https://example.com/docs"
        return stats

    monkeypatch.setattr(
        "docsync.cli.run_crawler",
        fake_run_crawler,
    )
    monkeypatch.setattr(
        "docsync.cli.CrawlDashboard",
        FakeDashboard,
    )

    result = main(
        [
            "https://example.com/docs",
            "--max-requests",
            "20",
            "--max-concurrency",
            "2",
            "--requests-per-minute",
            "20",
        ]
    )

    assert result == 0
    assert len(FakeDashboard.instances) == 1

    dashboard = FakeDashboard.instances[0]

    assert dashboard.started is True
    assert dashboard.finished is True
    assert dashboard.interrupted is False

    assert dashboard.snapshot.processed == 8
    assert dashboard.snapshot.saved == 5
    assert dashboard.snapshot.duplicate_content == 1
    assert dashboard.snapshot.incremental_skipped == 1
    assert dashboard.snapshot.rejected_urls == 2
    assert dashboard.snapshot.empty_pages == 3
    assert dashboard.snapshot.non_english == 4
    assert dashboard.snapshot.failed == 0

    assert capsys.readouterr().out == (
        "Finished: processed=8 saved=5 duplicate=1 "
        "incremental_skipped=1 non_english=4 failed=0\n"
    )


def test_cli_dashboard_uses_resolved_runtime_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_runtime(
        monkeypatch,
        tmp_path,
    )

    async def fake_run_crawler(
        start_url: str,
        **_: Any,
    ) -> CrawlStats:
        return CrawlStats(
            mode="playwright",
        )

    monkeypatch.setattr(
        "docsync.cli.run_crawler",
        fake_run_crawler,
    )
    monkeypatch.setattr(
        "docsync.cli.CrawlDashboard",
        FakeDashboard,
    )

    result = main(
        [
            "https://example.com/docs",
            "--mode",
            "playwright",
            "--browser-type",
            "firefox",
            "--show-browser",
            "--max-requests",
            "12",
            "--max-concurrency",
            "3",
            "--requests-per-minute",
            "18",
        ]
    )

    assert result == 0

    snapshot = FakeDashboard.instances[0].snapshot

    assert snapshot.site == SiteInformation.from_start_url(
        "https://example.com/docs",
        mode="playwright",
        language="en",
        robots_enabled=True,
        browser_type="firefox",
        headless=False,
    )
    assert snapshot.max_requests == 12
    assert snapshot.max_concurrency == 3
    assert snapshot.requests_per_minute == 18
    assert snapshot.output_dir == (tmp_path / "output").resolve()
    assert snapshot.state_dir == (tmp_path / "state").resolve()


def test_cli_preserves_failure_exit_code_and_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_runtime(
        monkeypatch,
        tmp_path,
    )

    async def fake_run_crawler(
        start_url: str,
        **_: Any,
    ) -> CrawlStats:
        return CrawlStats(
            mode="http",
            processed=2,
            saved=1,
            failed=1,
        )

    monkeypatch.setattr(
        "docsync.cli.run_crawler",
        fake_run_crawler,
    )
    monkeypatch.setattr(
        "docsync.cli.CrawlDashboard",
        FakeDashboard,
    )

    result = main(
        [
            "https://example.com/docs",
        ]
    )

    assert result == 1
    assert FakeDashboard.instances[0].finished is True
    assert FakeDashboard.instances[0].snapshot.failed == 1
    assert "failed=1" in capsys.readouterr().out


def test_cli_marks_dashboard_interrupted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_runtime(
        monkeypatch,
        tmp_path,
    )

    def fake_run_crawler(
        start_url: str,
        **_: Any,
    ) -> CrawlStats:
        raise KeyboardInterrupt

    monkeypatch.setattr(
        "docsync.cli.run_crawler",
        fake_run_crawler,
    )
    monkeypatch.setattr(
        "docsync.cli.CrawlDashboard",
        FakeDashboard,
    )

    with pytest.raises(KeyboardInterrupt):
        main(
            [
                "https://example.com/docs",
            ]
        )

    assert FakeDashboard.instances[0].started is True
    assert FakeDashboard.instances[0].finished is True
    assert FakeDashboard.instances[0].interrupted is True


def test_cli_finishes_dashboard_when_crawler_raises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_runtime(
        monkeypatch,
        tmp_path,
    )

    def fake_run_crawler(
        start_url: str,
        **_: Any,
    ) -> CrawlStats:
        raise RuntimeError("simulated crawler failure")

    monkeypatch.setattr(
        "docsync.cli.run_crawler",
        fake_run_crawler,
    )
    monkeypatch.setattr(
        "docsync.cli.CrawlDashboard",
        FakeDashboard,
    )

    with pytest.raises(
        RuntimeError,
        match="simulated crawler failure",
    ):
        main(
            [
                "https://example.com/docs",
            ]
        )

    dashboard = FakeDashboard.instances[0]

    assert dashboard.started is True
    assert dashboard.finished is True
    assert dashboard.snapshot.failed == 1


def test_cli_forwards_live_event_sink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from docsync.progress_events import CrawlEvent

    configure_runtime(
        monkeypatch,
        tmp_path,
    )

    captured_event_sink: object | None = None

    async def fake_run_crawler(
        start_url: str,
        event_sink: object | None = None,
        **_: Any,
    ) -> CrawlStats:
        nonlocal captured_event_sink

        captured_event_sink = event_sink

        assert callable(event_sink)

        event_sink(
            CrawlEvent(
                phase="Crawling",
                current_url="https://example.com/docs/page",
                current_title="Page",
                processed=1,
                saved=1,
                queued=4,
                discovered=5,
                active_requests=1,
                sitemap_urls=4,
                sitemap_files_checked=3,
                sitemap_files_found=1,
                sitemap_errors=2,
                site_title="Example Documentation",
            )
        )

        return CrawlStats(
            mode="http",
            processed=1,
            saved=1,
        )

    monkeypatch.setattr(
        "docsync.cli.run_crawler",
        fake_run_crawler,
    )
    monkeypatch.setattr(
        "docsync.cli.CrawlDashboard",
        FakeDashboard,
    )

    result = main(
        [
            "https://example.com/docs",
        ]
    )

    assert result == 0
    assert callable(captured_event_sink)

    dashboard = FakeDashboard.instances[0]

    assert dashboard.snapshot.current_url == ("https://example.com/docs/page")
    assert dashboard.snapshot.current_title == "Page"
    assert dashboard.snapshot.discovered == 5
    assert dashboard.snapshot.queued == 0
    assert dashboard.snapshot.active_requests == 0
    assert dashboard.snapshot.site.title == ("Example Documentation")
    assert dashboard.snapshot.site.sitemap_urls == 4
    assert dashboard.snapshot.site.sitemap_files_checked == 3
    assert dashboard.snapshot.site.sitemap_files_found == 1
    assert dashboard.snapshot.site.sitemap_errors == 2


def test_cli_finalization_resets_active_requests_and_queue(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from docsync.progress_events import CrawlEvent

    configure_runtime(
        monkeypatch,
        tmp_path,
    )

    async def fake_run_crawler(
        start_url: str,
        event_sink: object | None = None,
        **_: Any,
    ) -> CrawlStats:
        assert callable(event_sink)

        event_sink(
            CrawlEvent(
                phase="Downloading",
                current_url="https://example.com/docs/page",
                processed=1,
                queued=4,
                discovered=5,
                active_requests=1,
            )
        )

        return CrawlStats(
            mode="http",
            processed=1,
            saved=1,
        )

    monkeypatch.setattr(
        "docsync.cli.run_crawler",
        fake_run_crawler,
    )
    monkeypatch.setattr(
        "docsync.cli.CrawlDashboard",
        FakeDashboard,
    )

    result = main(
        [
            "https://example.com/docs",
        ]
    )

    assert result == 0

    dashboard = FakeDashboard.instances[0]

    assert dashboard.finished is True
    assert dashboard.snapshot.active_requests == 0
    assert dashboard.snapshot.queued == 0
    assert dashboard.snapshot.phase == "Finalizing"
