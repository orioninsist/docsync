"""Tests for typed crawler progress lifecycle events."""

from __future__ import annotations

from docsync.progress_events import CrawlEvent


def test_crawl_event_defaults_are_optional() -> None:
    event = CrawlEvent()

    assert event.phase is None
    assert event.current_url is None
    assert event.processed is None
    assert event.active_requests is None
    assert event.sitemap_urls is None


def test_crawl_event_stores_live_metrics() -> None:
    event = CrawlEvent(
        phase="Crawling",
        current_url="https://example.com/docs",
        current_title="Documentation",
        processed=3,
        saved=2,
        failed=1,
        queued=5,
        discovered=8,
        active_requests=2,
        sitemap_urls=7,
        sitemap_files_checked=3,
        sitemap_files_found=1,
        sitemap_errors=2,
        site_title="Example Documentation",
    )

    assert event.phase == "Crawling"
    assert event.current_url == "https://example.com/docs"
    assert event.current_title == "Documentation"
    assert event.processed == 3
    assert event.saved == 2
    assert event.failed == 1
    assert event.queued == 5
    assert event.discovered == 8
    assert event.active_requests == 2
    assert event.sitemap_urls == 7
    assert event.sitemap_files_checked == 3
    assert event.sitemap_files_found == 1
    assert event.sitemap_errors == 2
    assert event.site_title == "Example Documentation"
