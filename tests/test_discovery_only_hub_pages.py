"""Regression coverage for discovery-only documentation hub pages."""

from __future__ import annotations

from pathlib import Path

from docsync.crawler import build_scope_pattern, filter_discovered_urls

ROOT = Path(__file__).resolve().parents[1]
CRAWLER_PATH = ROOT / "src" / "docsync" / "crawler.py"



def test_discovered_urls_are_normalized_and_filtered() -> None:
    scope_pattern = build_scope_pattern("https://support.google.com/youtube")

    assert filter_discovered_urls(
        urls=[
            "https://support.google.com/youtube/topic/9257404?hl=en",
            "https://support.google.com/youtube/topic/9257404?hl=en#section",
            "https://support.google.com/youtube/article/123",
            "https://support.google.com/accounts/login",
            "https://example.com/youtube/outside",
            "https://support.google.com/youtube/file.pdf",
            "https://support.google.com/youtube#topic=9257498",
        ],
        base_url="https://support.google.com/youtube",
        scope_pattern=scope_pattern,
        should_skip_url=lambda _url: False,
    ) == [
        "https://support.google.com/youtube/topic/9257404?hl=en",
        "https://support.google.com/youtube/article/123",
    ]


def test_request_handler_discovers_before_first_export() -> None:
    source = CRAWLER_PATH.read_text(encoding="utf-8")

    discovery_position = source.index(
        "discovered_urls = await discover_and_enqueue_in_scope_links("
    )
    first_export_position = source.index("document = markdown_exporter.export(")

    assert discovery_position < first_export_position


def test_fallback_discovers_before_second_export() -> None:
    source = CRAWLER_PATH.read_text(encoding="utf-8")

    fallback_discovery_position = source.index(
        "fallback_urls = filter_discovered_urls("
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

    fallback_position = source.index("fallback_urls = filter_discovered_urls(")
    add_position = source.index(
        "await fallback_context.enqueue_links(",
        fallback_position,
    )
    export_position = source.index(
        "document = markdown_exporter.export(",
        add_position,
    )

    assert fallback_position < add_position
    assert add_position < export_position
