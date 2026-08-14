"""Default update-detection behavior contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from docsync.config import DEFAULT_REFRESH_HOURS, Settings
from docsync.incremental import (
    content_is_unchanged,
    filter_incremental_urls,
)


@dataclass(frozen=True, slots=True)
class IncrementalConfig:
    refresh_hours: int
    force_refresh: bool = False


@dataclass(slots=True)
class IncrementalStats:
    incremental_skipped: int = 0
    incremental_skipped_urls: set[str] = field(default_factory=set)


def test_default_refresh_window_is_disabled() -> None:
    assert DEFAULT_REFRESH_HOURS == 0


def test_environment_default_revalidates_pages(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setenv(
        "DOCSYNC_START_URL",
        "https://example.com/docs",
    )
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
    monkeypatch.delenv(
        "DOCSYNC_REFRESH_HOURS",
        raising=False,
    )
    monkeypatch.delenv(
        "DOCSYNC_FORCE_REFRESH",
        raising=False,
    )

    settings = Settings.from_environment()

    assert settings.refresh_hours == 0
    assert settings.force_refresh is False


def test_default_policy_does_not_skip_recent_url() -> None:
    url = "https://example.com/docs"
    stats = IncrementalStats()
    state = {
        url: {
            "saved_at": datetime.now(UTC).isoformat(),
            "filename": "docs.md",
            "content_hash": "old-hash",
        }
    }

    selected = filter_incremental_urls(
        [url],
        config=IncrementalConfig(
            refresh_hours=0,
        ),
        stats=stats,
        url_state=state,
    )

    assert selected == [url]
    assert stats.incremental_skipped == 0
    assert stats.incremental_skipped_urls == set()


def test_optional_refresh_window_still_skips_recent_url() -> None:
    url = "https://example.com/docs"
    stats = IncrementalStats()
    state = {
        url: {
            "saved_at": datetime.now(UTC).isoformat(),
            "filename": "docs.md",
            "content_hash": "old-hash",
        }
    }

    selected = filter_incremental_urls(
        [url],
        config=IncrementalConfig(
            refresh_hours=24,
        ),
        stats=stats,
        url_state=state,
    )

    assert selected == []
    assert stats.incremental_skipped == 1
    assert stats.incremental_skipped_urls == {url}


def test_changed_content_is_detected_after_revalidation() -> None:
    url = "https://example.com/docs"
    state = {
        url: {
            "saved_at": datetime.now(UTC).isoformat(),
            "filename": "docs.md",
            "content_hash": "old-hash",
        }
    }

    assert (
        content_is_unchanged(
            url=url,
            digest="new-hash",
            url_state=state,
        )
        is False
    )


def test_unchanged_content_is_not_rewritten_after_revalidation() -> None:
    url = "https://example.com/docs"
    state = {
        url: {
            "saved_at": datetime.now(UTC).isoformat(),
            "filename": "docs.md",
            "content_hash": "stable-hash",
        }
    }

    assert (
        content_is_unchanged(
            url=url,
            digest="stable-hash",
            url_state=state,
        )
        is True
    )
