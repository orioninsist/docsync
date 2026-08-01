"""Incremental synchronization state tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import docsync.incremental as incremental


@dataclass
class Config:
    refresh_hours: int = 24
    force_refresh: bool = False


@dataclass
class Stats:
    incremental_skipped: int = 0
    incremental_skipped_urls: set[str] = field(default_factory=set)


def test_content_hash_normalizes_newlines() -> None:
    assert incremental.content_hash(
        "# Page\r\n\r\nBody\r\n"
    ) == incremental.content_hash("# Page\n\nBody\n")


def test_recent_url_inside_refresh_window() -> None:
    now = datetime(
        2026,
        7,
        31,
        12,
        0,
        tzinfo=UTC,
    )

    state = {
        "https://example.com/docs": {
            "saved_at": (now - timedelta(hours=2)).isoformat(),
            "filename": "docs.md",
            "content_hash": "abc",
        }
    }

    assert incremental.is_recently_saved(
        "https://example.com/docs/",
        Config(refresh_hours=24),
        state,
        now=now,
    )


def test_expired_url_requires_refresh() -> None:
    now = datetime(
        2026,
        7,
        31,
        12,
        0,
        tzinfo=UTC,
    )

    state = {
        "https://example.com/docs": {
            "saved_at": (now - timedelta(hours=25)).isoformat(),
            "filename": "docs.md",
            "content_hash": "abc",
        }
    }

    assert not incremental.is_recently_saved(
        "https://example.com/docs",
        Config(refresh_hours=24),
        state,
        now=now,
    )


@pytest.mark.parametrize(
    "config",
    [
        Config(refresh_hours=0),
        Config(force_refresh=True),
    ],
)
def test_disabled_incremental_filter_requires_refresh(
    config: Config,
) -> None:
    state = {
        "https://example.com/docs": {
            "saved_at": datetime.now(UTC).isoformat(),
            "filename": "docs.md",
            "content_hash": "abc",
        }
    }

    assert not incremental.is_recently_saved(
        "https://example.com/docs",
        config,
        state,
    )


def test_filter_normalizes_deduplicates_and_records_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = Stats()

    monkeypatch.setattr(
        incremental,
        "is_recently_saved",
        lambda url, config, state: url.endswith("/recent"),
    )

    selected = incremental.filter_incremental_urls(
        [
            "https://example.com/a/",
            "https://example.com/a",
            "https://example.com/recent/",
            "https://example.com/b?utm_source=test",
        ],
        Config(),
        stats,
        {},
    )

    assert selected == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert stats.incremental_skipped == 1
    assert stats.incremental_skipped_urls == {
        "https://example.com/recent",
    }


def test_record_success_updates_legacy_stores(
    tmp_path: Path,
) -> None:
    hashes: dict[str, str] = {}
    state: dict[str, dict[str, str]] = {}

    saved_at = datetime(
        2026,
        7,
        31,
        12,
        30,
        tzinfo=UTC,
    )

    incremental.record_incremental_success(
        url="https://example.com/docs/",
        output_path=tmp_path / "docs.md",
        digest="ABC123",
        hashes=hashes,
        url_state=state,
        saved_at=saved_at,
    )

    assert hashes == {"abc123": "https://example.com/docs"}
    assert state == {
        "https://example.com/docs": {
            "saved_at": saved_at.isoformat(),
            "filename": "docs.md",
            "content_hash": "abc123",
        }
    }


def test_content_is_unchanged() -> None:
    state = {
        "https://example.com/docs": {
            "saved_at": datetime.now(UTC).isoformat(),
            "filename": "docs.md",
            "content_hash": "abc123",
        }
    }

    assert incremental.content_is_unchanged(
        url="https://example.com/docs/",
        digest="ABC123",
        url_state=state,
    )


def test_loaders_do_not_modify_invalid_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    content_hash_path = tmp_path / "content_hashes.json"
    url_state_path = tmp_path / "url_state.json"

    content_hash_path.write_text(
        "{invalid",
        encoding="utf-8",
    )
    url_state_path.write_text(
        "{invalid",
        encoding="utf-8",
    )

    content_hash_bytes = content_hash_path.read_bytes()
    url_state_bytes = url_state_path.read_bytes()

    monkeypatch.setattr(
        incremental,
        "CONTENT_HASH_FILE",
        content_hash_path,
    )
    monkeypatch.setattr(
        incremental,
        "URL_STATE_FILE",
        url_state_path,
    )

    assert incremental.load_content_hashes() == {}
    assert incremental.load_url_state() == {}

    assert content_hash_path.read_bytes() == content_hash_bytes
    assert url_state_path.read_bytes() == url_state_bytes


def test_url_state_loader_discards_invalid_records(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "url_state.json"

    path.write_text(
        json.dumps(
            {
                "https://example.com/valid": {
                    "saved_at": ("2026-07-31T12:00:00+00:00"),
                    "filename": "valid.md",
                    "content_hash": "abc",
                },
                "https://example.com/missing-time": {
                    "filename": "invalid.md",
                },
                "invalid-record": "not-an-object",
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        incremental,
        "URL_STATE_FILE",
        path,
    )

    assert incremental.load_url_state() == {
        "https://example.com/valid": {
            "saved_at": ("2026-07-31T12:00:00+00:00"),
            "filename": "valid.md",
            "content_hash": "abc",
        }
    }
