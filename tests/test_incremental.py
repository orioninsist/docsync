"""Incremental synchronization state tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import docsync.incremental as incremental


@dataclass
class Stats:
    incremental_skipped: int = 0
    incremental_skipped_urls: set[str] = field(default_factory=set)


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
            "etag": "",
            "last_modified": "",
        }
    }

    assert incremental.is_recently_saved(
        "https://example.com/docs/",
        24,
        False,
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
        24,
        False,
        state,
        now=now,
    )


@pytest.mark.parametrize(
    ("refresh_hours", "force_refresh"),
    [
        (0, False),
        (24, True),
    ],
)
def test_disabled_incremental_filter_requires_refresh(
    refresh_hours: int,
    force_refresh: bool,
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
        refresh_hours,
        force_refresh,
        state,
    )


def test_filter_normalizes_deduplicates_and_records_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = Stats()

    monkeypatch.setattr(
        incremental,
        "is_recently_saved",
        lambda url, refresh_hours, force_refresh, state: url.endswith("/recent"),
    )

    selected = incremental.filter_incremental_urls(
        [
            "https://example.com/a/",
            "https://example.com/a",
            "https://example.com/recent/",
            "https://example.com/b?utm_source=test",
        ],
        24,
        False,
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


def test_record_success_updates_state_stores(
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
            "etag": "",
            "last_modified": "",
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
            "etag": "",
            "last_modified": "",
        }
    }


def test_conditional_request_headers_use_saved_validators() -> None:
    url = "https://example.com/docs"
    state = {
        url: {
            "saved_at": datetime.now(UTC).isoformat(),
            "filename": "docs.md",
            "content_hash": "abc123",
            "etag": '"docs-v1"',
            "last_modified": "Fri, 18 Sep 2026 12:00:00 GMT",
        }
    }

    assert incremental.conditional_request_headers(
        url=url,
        url_state=state,
    ) == {
        "If-None-Match": '"docs-v1"',
        "If-Modified-Since": "Fri, 18 Sep 2026 12:00:00 GMT",
    }


def test_force_refresh_disables_conditional_request_headers() -> None:
    url = "https://example.com/docs"
    state = {
        url: {
            "saved_at": datetime.now(UTC).isoformat(),
            "filename": "docs.md",
            "content_hash": "abc123",
            "etag": '"docs-v1"',
            "last_modified": "",
        }
    }

    assert (
        incremental.conditional_request_headers(
            url=url,
            url_state=state,
            force_refresh=True,
        )
        == {}
    )


def test_response_validators_are_extracted_case_insensitively() -> None:
    class Headers:
        def __init__(self) -> None:
            self.values = {
                "etag": '"docs-v2"',
                "last-modified": "Sat, 19 Sep 2026 12:00:00 GMT",
            }

        def get(self, key: str):
            return self.values.get(key.lower())

    assert incremental.response_validators(Headers()) == (
        '"docs-v2"',
        "Sat, 19 Sep 2026 12:00:00 GMT",
    )



def test_flat_per_host_state_files(tmp_path: Path) -> None:
    hashes = {"abc123": "https://developers.openai.com/docs"}
    state = {
        "https://developers.openai.com/docs": {
            "saved_at": "2026-09-22T12:00:00+00:00",
            "filename": "docs.md",
            "content_hash": "abc123",
            "etag": "",
            "last_modified": "",
        }
    }

    incremental.save_content_hashes(
        hashes,
        tmp_path,
        "developers.openai.com",
    )
    incremental.save_url_state(
        state,
        tmp_path,
        "developers.openai.com",
    )

    assert (tmp_path / "developers.openai.com_content_hashes.json").is_file()
    assert (tmp_path / "developers.openai.com_url_state.json").is_file()
    assert not (tmp_path / "developers.openai.com").exists()
    assert incremental.load_content_hashes(
        tmp_path,
        "developers.openai.com",
    ) == hashes
    assert incremental.load_url_state(
        tmp_path,
        "developers.openai.com",
    ) == state


def test_state_files_are_isolated_by_hostname(tmp_path: Path) -> None:
    incremental.save_content_hashes(
        {"one": "https://one.example/docs"},
        tmp_path,
        "one.example",
    )
    incremental.save_content_hashes(
        {"two": "https://two.example/docs"},
        tmp_path,
        "two.example",
    )

    assert incremental.load_content_hashes(tmp_path, "one.example") == {
        "one": "https://one.example/docs"
    }
    assert incremental.load_content_hashes(tmp_path, "two.example") == {
        "two": "https://two.example/docs"
    }



def test_record_success_replaces_stale_hash_for_same_url(tmp_path: Path) -> None:
    output_path = tmp_path / "docs.md"
    hashes = {
        "oldhash": "https://example.com/docs",
        "otherhash": "https://example.com/other",
    }
    url_state = {
        "https://example.com/docs": {
            "saved_at": "2026-09-22T00:00:00+00:00",
            "filename": "docs.md",
            "content_hash": "oldhash",
            "etag": "",
            "last_modified": "",
        }
    }

    incremental.record_incremental_success(
        url="https://example.com/docs",
        output_path=output_path,
        digest="NEWHASH",
        hashes=hashes,
        url_state=url_state,
    )

    assert "oldhash" not in hashes
    assert hashes["newhash"] == "https://example.com/docs"
    assert hashes["otherhash"] == "https://example.com/other"
    assert url_state["https://example.com/docs"]["content_hash"] == "newhash"


def test_record_success_keeps_single_hash_when_content_is_unchanged(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "docs.md"
    hashes = {"samehash": "https://example.com/docs"}
    url_state: dict[str, dict[str, str]] = {}

    incremental.record_incremental_success(
        url="https://example.com/docs",
        output_path=output_path,
        digest="SAMEHASH",
        hashes=hashes,
        url_state=url_state,
    )

    assert hashes == {"samehash": "https://example.com/docs"}
