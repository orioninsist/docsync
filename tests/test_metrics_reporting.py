"""Canonical crawl metrics and reporting contracts."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from docsync.metrics import (
    CRAWL_REPORT_FILENAME,
    CrawlStats,
    build_crawl_report,
    write_crawl_report,
)


def fixed_started_at() -> datetime:
    return datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


def fixed_finished_at() -> datetime:
    return datetime(2026, 8, 1, 0, 1, tzinfo=UTC)


def test_crawl_stats_defaults_are_zeroed() -> None:
    stats = CrawlStats(
        mode="http",
        started_at=fixed_started_at(),
    )

    assert stats.processed == 0
    assert stats.saved == 0
    assert stats.duplicate_content == 0
    assert stats.rejected_urls == 0
    assert stats.empty_pages == 0
    assert stats.non_english == 0
    assert stats.failed == 0
    assert stats.sitemap_urls == 0
    assert stats.sitemap_files_checked == 0
    assert stats.sitemap_files_found == 0
    assert stats.sitemap_errors == 0
    assert stats.incremental_skipped == 0
    assert stats.incremental_skipped_urls == set()
    assert stats.exit_code == 0


def test_incremental_skip_count_tracks_unique_urls() -> None:
    stats = CrawlStats(
        mode="http",
        started_at=fixed_started_at(),
    )

    assert stats.record_incremental_skip("https://example.com/a") is True
    assert stats.record_incremental_skip("https://example.com/a") is False
    assert stats.record_incremental_skip(" https://example.com/b ") is True
    assert stats.record_incremental_skip("   ") is False

    assert stats.incremental_skipped == 2
    assert stats.incremental_skipped_urls == {
        "https://example.com/a",
        "https://example.com/b",
    }


def test_finished_summary_preserves_canonical_contract() -> None:
    stats = CrawlStats(
        mode="http",
        started_at=fixed_started_at(),
        processed=8,
        saved=5,
        duplicate_content=1,
        incremental_skipped=2,
        non_english=3,
        failed=4,
    )

    assert stats.finished_summary() == (
        "Finished: processed=8 saved=5 duplicate=1 "
        "incremental_skipped=2 non_english=3 failed=4"
    )
    assert stats.exit_code == 1


def test_as_dict_preserves_legacy_metric_names() -> None:
    stats = CrawlStats(
        mode="playwright",
        started_at=fixed_started_at(),
        processed=10,
        saved=6,
        duplicate_content=2,
        rejected_urls=1,
        empty_pages=1,
        non_english=3,
        failed=4,
        sitemap_urls=5,
        sitemap_files_checked=6,
        sitemap_files_found=7,
        sitemap_errors=8,
        incremental_skipped=2,
        incremental_skipped_urls={
            "https://example.com/b",
            "https://example.com/a",
        },
    )

    payload = stats.as_dict(finished_at=fixed_finished_at())

    assert payload == {
        "started_at": "2026-08-01T00:00:00+00:00",
        "finished_at": "2026-08-01T00:01:00+00:00",
        "mode": "playwright",
        "processed": 10,
        "saved": 6,
        "duplicate_content": 2,
        "rejected_urls": 1,
        "empty_pages": 1,
        "non_english": 3,
        "failed": 4,
        "sitemap_urls": 5,
        "sitemap_files_checked": 6,
        "sitemap_files_found": 7,
        "sitemap_errors": 8,
        "incremental_skipped": 2,
        "incremental_skipped_urls": [
            "https://example.com/a",
            "https://example.com/b",
        ],
    }


def test_build_report_serializes_configuration_values(tmp_path: Path) -> None:
    stats = CrawlStats(
        mode="http",
        started_at=fixed_started_at(),
    )

    report = build_crawl_report(
        stats=stats,
        configuration={
            "output_dir": tmp_path / "output",
            "max_requests": 10,
            "force_refresh": False,
            "allowed_modes": {"playwright", "http"},
        },
        finished_at=fixed_finished_at(),
    )

    assert report["configuration"] == {
        "allowed_modes": ["http", "playwright"],
        "force_refresh": False,
        "max_requests": 10,
        "output_dir": str(tmp_path / "output"),
    }
    assert report["mode"] == "http"
    assert report["finished_at"] == "2026-08-01T00:01:00+00:00"


def test_write_crawl_report_uses_atomic_replacement(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    stats = CrawlStats(
        mode="http",
        started_at=fixed_started_at(),
        processed=1,
        saved=1,
    )

    report_path = write_crawl_report(
        output_dir=output_dir,
        stats=stats,
        configuration={"max_requests": 1},
        finished_at=fixed_finished_at(),
    )

    assert report_path == output_dir.resolve() / CRAWL_REPORT_FILENAME
    assert report_path.is_file()
    assert not report_path.with_suffix(".json.tmp").exists()

    payload = json.loads(report_path.read_text(encoding="utf-8"))

    assert payload["processed"] == 1
    assert payload["saved"] == 1
    assert payload["configuration"]["max_requests"] == 1


def test_repeated_report_write_replaces_previous_payload(tmp_path: Path) -> None:
    first = CrawlStats(
        mode="http",
        started_at=fixed_started_at(),
        processed=1,
    )
    second = CrawlStats(
        mode="http",
        started_at=fixed_started_at(),
        processed=2,
        saved=1,
    )

    first_path = write_crawl_report(
        output_dir=tmp_path,
        stats=first,
        finished_at=fixed_finished_at(),
    )
    second_path = write_crawl_report(
        output_dir=tmp_path,
        stats=second,
        finished_at=fixed_finished_at(),
    )

    assert first_path == second_path

    payload = json.loads(second_path.read_text(encoding="utf-8"))
    assert payload["processed"] == 2
    assert payload["saved"] == 1


def test_report_write_failure_removes_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = CrawlStats(
        mode="http",
        started_at=fixed_started_at(),
    )
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    report_path = output_dir / CRAWL_REPORT_FILENAME
    temporary_path = report_path.with_suffix(".json.tmp")

    original_replace = Path.replace

    def failing_replace(self: Path, target: Path) -> Path:
        if self == temporary_path:
            raise OSError("simulated report replacement failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", failing_replace)

    with pytest.raises(
        OSError,
        match="simulated report replacement failure",
    ):
        write_crawl_report(
            output_dir=output_dir,
            stats=stats,
            finished_at=fixed_finished_at(),
        )

    assert not report_path.exists()
    assert not temporary_path.exists()


def test_empty_report_filename_is_rejected(tmp_path: Path) -> None:
    stats = CrawlStats(
        mode="http",
        started_at=fixed_started_at(),
    )

    with pytest.raises(ValueError, match="filename must not be empty"):
        write_crawl_report(
            output_dir=tmp_path,
            stats=stats,
            filename=" ",
        )
