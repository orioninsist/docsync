from __future__ import annotations

import gzip
import json
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import docsync.incremental as incremental
from docsync.markdown import MarkdownExporter
from docsync.metrics import CrawlStats
from docsync.sitemap import (
    decode_sitemap_payload,
    extract_robots_sitemaps,
    sitemap_xml_locations,
)
from docsync.url_security import (
    SameOriginRedirectHandler,
    normalize_url,
    normalized_http_origin,
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


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://example.com/docs",
            ("https", "example.com", 443),
        ),
        (
            "http://example.com/path",
            ("http", "example.com", 80),
        ),
        (
            "https://EXAMPLE.COM.:8443/path",
            ("https", "example.com", 8443),
        ),
    ],
)
def test_normalized_http_origin_uses_effective_port(
    url: str,
    expected: tuple[str, str, int],
) -> None:
    assert normalized_http_origin(url) == expected


def test_same_origin_redirect_handler_accepts_same_origin() -> None:
    handler = SameOriginRedirectHandler(
        "https://example.com/docs",
    )

    assert (
        handler.validate_redirect("https://example.com/other")
        == "https://example.com/other"
    )


@pytest.mark.parametrize(
    "redirect_url",
    [
        "https://other.example/docs",
        "http://example.com/docs",
        "https://example.com:444/docs",
        "file:///etc/passwd",
    ],
)
def test_same_origin_redirect_handler_rejects_unsafe_redirects(
    redirect_url: str,
) -> None:
    handler = SameOriginRedirectHandler(
        "https://example.com/docs",
    )

    expected_exception = (
        ValueError if redirect_url.startswith("file:") else urllib.error.HTTPError
    )

    with pytest.raises(expected_exception):
        handler.validate_redirect(redirect_url)


def test_decode_sitemap_payload_decodes_plain_xml() -> None:
    payload = b'<?xml version="1.0"?><urlset></urlset>'

    assert decode_sitemap_payload(
        payload,
        "https://example.com/sitemap.xml",
    ) == payload.decode("utf-8")


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/sitemap.xml.gz",
        "https://example.com/download",
    ],
)
def test_decode_sitemap_payload_decompresses_gzip(
    url: str,
) -> None:
    expected = '<?xml version="1.0"?><urlset></urlset>'
    payload = gzip.compress(expected.encode("utf-8"))

    assert decode_sitemap_payload(payload, url) == expected


def test_extract_robots_sitemaps_handles_comments_relative_urls_and_duplicates() -> (
    None
):
    robots_text = """
    User-agent: *
    Disallow: /private

    Sitemap: /sitemap.xml
    sitemap: https://example.com/sitemap-news.xml # inline comment
    Sitemap: /sitemap.xml
    Sitemap:
    """

    assert extract_robots_sitemaps(
        robots_text,
        "https://example.com/",
    ) == [
        "https://example.com/sitemap.xml",
        "https://example.com/sitemap-news.xml",
    ]


@pytest.mark.parametrize(
    ("xml_text", "expected_type", "expected_locations"),
    [
        (
            """
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                <url><loc>https://example.com/a</loc></url>
                <url><loc> https://example.com/b </loc></url>
            </urlset>
            """,
            "urlset",
            [
                "https://example.com/a",
                "https://example.com/b",
            ],
        ),
        (
            """
            <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
                <sitemap><loc>https://example.com/one.xml</loc></sitemap>
                <sitemap><loc>https://example.com/two.xml</loc></sitemap>
            </sitemapindex>
            """,
            "index",
            [
                "https://example.com/one.xml",
                "https://example.com/two.xml",
            ],
        ),
    ],
)
def test_sitemap_xml_locations_extracts_supported_documents(
    xml_text: str,
    expected_type: str,
    expected_locations: list[str],
) -> None:
    sitemap_type, locations = sitemap_xml_locations(xml_text)

    assert sitemap_type == expected_type
    assert locations == expected_locations


def test_normalize_markdown_normalizes_newlines_and_spacing() -> None:
    value = "  # Title  \r\n\r\n\r\n\r\nParagraph   \rMore\t \n"

    assert MarkdownExporter._normalize_markdown(value) == (
        "# Title\n\nParagraph\nMore\n"
    )


def test_filter_incremental_urls_normalizes_deduplicates_and_records_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SimpleNamespace(
        refresh_hours=24,
        force_refresh=False,
    )
    stats = CrawlStats(
        started_at="2026-01-01T00:00:00Z",
        mode="http",
    )
    url_state: dict[str, dict[str, str]] = {}

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
        config,
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


def test_save_content_hashes_writes_sorted_json_atomically(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    hash_file = tmp_path / "state" / "content_hashes.json"
    hash_file.parent.mkdir(parents=True)

    monkeypatch.setattr(
        incremental,
        "CONTENT_HASH_FILE",
        hash_file,
    )

    hashes = {
        "https://example.com/b": "hash-b",
        "https://example.com/a": "hash-a",
    }

    incremental.save_content_hashes(hashes)

    assert json.loads(hash_file.read_text(encoding="utf-8")) == hashes
    assert not hash_file.with_suffix(".tmp").exists()


def test_load_content_hashes_returns_empty_for_invalid_json(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    hash_file = tmp_path / "content_hashes.json"
    hash_file.write_text("{invalid", encoding="utf-8")

    monkeypatch.setattr(
        incremental,
        "CONTENT_HASH_FILE",
        hash_file,
    )

    assert incremental.load_content_hashes() == {}


def test_load_content_hashes_discards_non_string_entries(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    hash_file = tmp_path / "content_hashes.json"
    hash_file.write_text(
        json.dumps(
            {
                "https://example.com/a": "hash-a",
                "https://example.com/b": 123,
                "invalid": None,
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        incremental,
        "CONTENT_HASH_FILE",
        hash_file,
    )

    loaded: Any = incremental.load_content_hashes()

    assert loaded == {
        "https://example.com/a": "hash-a",
    }
