from __future__ import annotations

from pathlib import Path

import pytest

import docsync.incremental as incremental
from docsync.markdown import MarkdownExporter
from docsync.metrics import CrawlStats
from docsync.url_security import (
    normalize_url,
    validated_http_url,
)


@pytest.mark.parametrize(
    ("raw_url", "expected"),
    [
        (
            "HTTPS://EXAMPLE.COM:443/docs//guide/?utm_source=test&b=2&a=1#section",
            "https://example.com/docs/guide?a=1&b=2",
        ),
        (
            "http://EXAMPLE.COM:80/",
            "http://example.com/",
        ),
        (
            "https://example.com/path/?fbclid=tracking&keep=value",
            "https://example.com/path?keep=value",
        ),
        (
            "https://example.com/path/",
            "https://example.com/path",
        ),
    ],
)
def test_normalize_url_removes_tracking_and_normalizes_structure(
    raw_url: str,
    expected: str,
) -> None:
    assert normalize_url(raw_url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://example.com/path",
        "HTTPS://example.com:443/docs",
    ],
)
def test_validated_http_url_accepts_http_and_https(url: str) -> None:
    assert validated_http_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/file",
        "javascript:alert(1)",
        "https:///missing-host",
        "https://user@example.com/",
        "https://user:password@example.com/",
        "https://example.com:invalid/",
    ],
)
def test_validated_http_url_rejects_unsafe_values(url: str) -> None:
    with pytest.raises(ValueError):
        validated_http_url(url)



def test_normalize_markdown_normalizes_newlines_and_spacing() -> None:
    value = "  # Title  \r\n\r\n\r\n\r\nParagraph   \rMore\t \n"

    assert MarkdownExporter._normalize_markdown(value) == (
        "# Title\n\nParagraph\nMore\n"
    )


def test_filter_incremental_urls_normalizes_deduplicates_and_records_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stats = CrawlStats(mode="http")
    url_state: dict[str, dict[str, str]] = {}

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
        url_state,
    )

    assert selected == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert stats.incremental_skipped_urls == {
        "https://example.com/recent",
    }
    assert stats.incremental_skipped == 1


def test_markdown_exporter_uses_atomic_replacement(
    tmp_path: Path,
) -> None:
    output_directory = tmp_path / "markdown"
    exporter = MarkdownExporter(output_directory)
    target = output_directory / "documentation.md"

    MarkdownExporter._atomic_write(
        output_path=target,
        content="# Documentation\n",
    )

    assert target.parent == output_directory
    assert target.read_text(encoding="utf-8") == "# Documentation\n"
    assert not target.with_suffix(".md.tmp").exists()

    MarkdownExporter._atomic_write(
        output_path=target,
        content="# Updated Documentation\n",
    )

    assert target.read_text(encoding="utf-8") == ("# Updated Documentation\n")
    assert not target.with_suffix(".md.tmp").exists()

    del exporter


