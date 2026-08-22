"""Lifecycle contracts for handler-discovered request insertion."""

from __future__ import annotations

from pathlib import Path

CRAWLER_PATH = Path("src/docsync/crawler.py")
RUNTIME_PATH = Path("src/docsync/crawler_runtime.py")


def _source() -> str:
    return CRAWLER_PATH.read_text(encoding="utf-8")


def test_primary_links_use_context_transaction() -> None:
    source = _source()

    assert source.count("await queue_context.add_requests(") == 1


def test_fallback_links_use_context_transaction() -> None:
    source = _source()

    assert source.count("await fallback_context.add_requests(") == 1


def test_handler_does_not_bypass_context_lifecycle() -> None:
    source = _source()

    assert "await crawler.add_requests(" not in source
    assert "await request_manager.add_requests(" not in source
    assert "async def enqueue_discovered_urls(" not in source


def test_throttling_manager_remains_crawler_request_manager() -> None:
    crawler_source = _source()
    runtime_source = RUNTIME_PATH.read_text(encoding="utf-8")

    assert "request_manager = ThrottlingRequestManager(" in runtime_source
    assert "inner=request_queue" in runtime_source
    assert crawler_source.count("request_manager=request_manager") == 2


def test_primary_discovery_precedes_url_language_rejection() -> None:
    source = _source()

    discovery = source.index("discovered_urls = extract_in_scope_links(")
    insertion = source.index(
        "await queue_context.add_requests(",
        discovery,
    )
    detection = source.index(
        "language_decision = language_detector.detect_from_html(",
        insertion,
    )

    assert discovery < insertion < detection


def test_primary_discovery_precedes_text_language_rejection() -> None:
    source = _source()

    insertion = source.index("await queue_context.add_requests(")
    rejection = source.index(
        "language_decision = language_detector.detect_from_html(",
        insertion,
    )

    assert insertion < rejection


def test_fallback_discovery_precedes_language_rejection() -> None:
    source = _source()

    discovery = source.index("fallback_urls = extract_in_scope_links(")
    insertion = source.index(
        "await fallback_context.add_requests(",
        discovery,
    )
    rejection = source.index(
        "fallback_language_decision =",
        insertion,
    )

    assert discovery < insertion < rejection
