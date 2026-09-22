"""Lifecycle contracts for handler-discovered request insertion."""

from __future__ import annotations

from pathlib import Path

CRAWLER_PATH = Path("src/docsync/crawler.py")
RUNTIME_PATH = Path("src/docsync/crawler_runtime.py")
ENGINE_PATH = Path("src/docsync/crawl_engine.py")


def _source() -> str:
    return CRAWLER_PATH.read_text(encoding="utf-8")


def test_primary_links_use_crawlee_native_discovery() -> None:
    source = _source()

    assert "await context.extract_links(" in source
    assert "await context.enqueue_links(" in source


def test_adaptive_renderers_share_native_enqueue() -> None:
    source = _source()

    assert source.count("await context.enqueue_links(") == 1
    assert "fallback_context" not in source


def test_handler_does_not_bypass_context_lifecycle() -> None:
    source = _source()

    assert "await crawler.add_requests(" not in source
    assert "await request_manager.add_requests(" not in source
    assert "async def enqueue_discovered_urls(" not in source


def test_throttling_manager_remains_crawler_request_manager() -> None:
    runtime_source = RUNTIME_PATH.read_text(encoding="utf-8")

    assert "request_manager = ThrottlingRequestManager(" in runtime_source
    assert "inner=request_queue" in runtime_source
    engine_source = ENGINE_PATH.read_text(encoding="utf-8")
    assert '"request_manager": runtime.request_manager' in engine_source
    assert "request_manager=runtime.request_manager" in engine_source


def test_primary_discovery_precedes_url_language_rejection() -> None:
    source = _source()
    discovery = source.index("discovered_urls = await discover_and_enqueue_in_scope_links(")
    detection = source.index("language_decision = language_detector.detect_from_html(", discovery)
    assert discovery < detection


def test_primary_discovery_precedes_text_language_rejection() -> None:
    source = _source()
    discovery = source.index("discovered_urls = await discover_and_enqueue_in_scope_links(")
    rejection = source.index("language_decision = language_detector.detect_from_html(", discovery)
    assert discovery < rejection


def test_adaptive_discovery_has_no_separate_fallback_queue_path() -> None:
    source = _source()
    assert "fallback_context" not in source
    assert source.count("discover_and_enqueue_in_scope_links(") == 2
