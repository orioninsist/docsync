"""Regression tests for language-independent link discovery."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRAWLER = ROOT / "src/docsync/crawler.py"
INVENTORY = ROOT / "src/docsync/inventory.py"


def _function_source(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            segment = ast.get_source_segment(source, node)
            assert segment is not None
            return segment
    raise AssertionError(name)


def test_main_handler_discovers_before_language_rejection() -> None:
    source = _function_source(CRAWLER, "request_handler")
    discovery = source.index("discovered_urls = await discover_and_enqueue_in_scope_links(")
    detection = source.index("language_decision = language_detector.detect_from_html(")
    assert discovery < detection


def test_adaptive_renderers_share_language_independent_discovery() -> None:
    source = _function_source(CRAWLER, "request_handler")
    assert source.count("discover_and_enqueue_in_scope_links(") == 1
    assert '"outcome": "non_english"' in source


def test_inventory_discovers_before_language_classification() -> None:
    source = _function_source(INVENTORY, "request_handler")
    discovery = source.index("discovered_links = await discover_and_enqueue_in_scope_links(")
    detection = source.index("language_decision = detector.detect_from_html(")
    assert discovery < detection


def test_skip_log_records_completed_discovery() -> None:
    source = CRAWLER.read_text(encoding="utf-8")
    assert "Non-English page skipped after discovery:" in source
