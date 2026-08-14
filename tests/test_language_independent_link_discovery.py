"""Regression tests for language-independent link discovery."""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CRAWLER_PATH = PROJECT_ROOT / "src/docsync/crawler.py"
INVENTORY_PATH = PROJECT_ROOT / "src/docsync/inventory.py"


def _async_function_source(
    path: Path,
    function_name: str,
) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == function_name:
            segment = ast.get_source_segment(source, node)

            if segment is None:
                raise AssertionError(f"Could not extract source for {function_name}")

            return segment

    raise AssertionError(f"Function not found: {function_name}")


def test_main_handler_discovers_before_url_language_rejection() -> None:
    source = _async_function_source(
        CRAWLER_PATH,
        "request_handler",
    )

    discovery = source.index("discovered_urls = extract_in_scope_links(")
    enqueue = source.index("await queue_context.add_requests(")
    rejection = source.index("if is_explicitly_non_english_url(effective_url):")

    assert discovery < enqueue < rejection


def test_main_handler_discovers_before_text_language_rejection() -> None:
    source = _async_function_source(
        CRAWLER_PATH,
        "request_handler",
    )

    enqueue = source.index("await queue_context.add_requests(")
    detection = source.index("language_decision = language_detector.detect_from_html(")

    assert enqueue < detection


def test_fallback_discovers_before_language_rejection() -> None:
    source = _async_function_source(
        CRAWLER_PATH,
        "request_handler",
    )

    fallback_start = source.index("fallback_html = await render_url_html(")
    fallback_source = source[fallback_start:]

    discovery = fallback_source.index("fallback_urls = extract_in_scope_links(")
    enqueue = fallback_source.index("await fallback_context.add_requests(")
    detection = fallback_source.index(
        "fallback_language_decision = language_detector.detect_from_html("
    )

    assert discovery < enqueue < detection


def test_inventory_discovers_before_language_classification() -> None:
    source = _async_function_source(
        INVENTORY_PATH,
        "request_handler",
    )

    discovery = source.index("discovered_links = extract_in_scope_links(")
    enqueue = source.index("await context.add_requests(queued_urls)")
    detection = source.index("language_decision = detector.detect_from_html(")

    assert discovery < enqueue < detection


def test_skip_logs_record_completed_discovery() -> None:
    source = CRAWLER_PATH.read_text(encoding="utf-8")

    assert "Explicitly non-English page skipped after discovery:" in source
    assert "Non-English page skipped after discovery:" in source
    assert "Non-English fallback page skipped after discovery:" in source
