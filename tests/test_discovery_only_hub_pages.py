"""Regression coverage for discovery-only documentation hub pages."""

from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup

from docsync.crawler import (
    build_scope_pattern,
    extract_in_scope_links,
)

ROOT = Path(__file__).resolve().parents[1]
CRAWLER_PATH = ROOT / "src" / "docsync" / "crawler.py"


def test_extract_in_scope_links_normalizes_and_filters() -> None:
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <a href="/youtube/topic/9257404?hl=en">First</a>
            <a href="/youtube/topic/9257404?hl=en#section">Duplicate</a>
            <a href="https://support.google.com/youtube/article/123">Article</a>
            <a href="/accounts/login">Login</a>
            <a href="https://example.com/youtube/outside">Outside</a>
            <a href="/youtube/file.pdf">PDF</a>
            <a href="#topic=9257498">Fragment-only</a>
          </body>
        </html>
        """,
        "html.parser",
    )

    scope_pattern = build_scope_pattern("https://support.google.com/youtube")

    assert extract_in_scope_links(
        soup=soup,
        base_url="https://support.google.com/youtube",
        scope_pattern=scope_pattern,
    ) == [
        "https://support.google.com/youtube/topic/9257404?hl=en",
        "https://support.google.com/youtube/article/123",
    ]


def test_request_handler_discovers_before_first_export() -> None:
    source = CRAWLER_PATH.read_text(encoding="utf-8")

    discovery_position = source.index("discovered_urls = extract_in_scope_links(")
    first_export_position = source.index("document = markdown_exporter.export(")

    assert discovery_position < first_export_position


def test_fallback_discovers_before_second_export() -> None:
    source = CRAWLER_PATH.read_text(encoding="utf-8")

    fallback_discovery_position = source.index(
        "fallback_urls = extract_in_scope_links("
    )
    fallback_export_position = source.index(
        "document = markdown_exporter.export(",
        fallback_discovery_position,
    )

    assert fallback_discovery_position < fallback_export_position


def test_discovery_only_pages_are_not_raised_as_failures() -> None:
    source = CRAWLER_PATH.read_text(encoding="utf-8")

    assert source.count('"Discovery-only page processed: "') == 2
    assert "and discovered_link_count > 0" in source
    assert "stats.empty_pages += 1" in source
    assert "stats.processed += 1" in source
    assert "return" in source


def test_browser_fallback_links_enter_request_queue_before_export() -> None:
    source = CRAWLER_PATH.read_text(encoding="utf-8")

    add_position = source.index("await fallback_context.add_requests(")
    export_position = source.index(
        "document = markdown_exporter.export(",
        add_position,
    )

    assert add_position < export_position
