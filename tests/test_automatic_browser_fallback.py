"""Automatic HTTP-to-Playwright fallback contracts."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CRAWLER_PATH = ROOT / "src" / "docsync" / "crawler.py"
RENDERING_PATH = ROOT / "src" / "docsync" / "playwright_rendering.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tree(path: Path) -> ast.Module:
    return ast.parse(
        _source(path),
        filename=str(path),
    )


def test_crawlee_url_renderer_exists() -> None:
    functions = {
        node.name
        for node in _tree(RENDERING_PATH).body
        if isinstance(node, ast.AsyncFunctionDef)
    }

    assert "render_url_with_crawlee" in functions


def test_fallback_renderer_uses_crawlee_playwright_crawler() -> None:
    source = _source(RENDERING_PATH)

    assert "PlaywrightCrawler" in source
    assert "async_playwright" not in source
    assert "await crawler.run([url])" in source


def test_http_empty_content_activates_browser_fallback() -> None:
    source = _source(CRAWLER_PATH)

    assert "HTTP extraction returned no meaningful content" in source
    assert '"No meaningful Markdown content found:"' in source
    assert 'resolved_mode != "http"' in source
    assert "fallback_html, fallback_links = await render_url_with_crawlee(" in source


def test_rendered_html_is_exported_as_markdown() -> None:
    tree = _tree(CRAWLER_PATH)

    export_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "export"
    ]

    assert len(export_calls) >= 2
    assert "used_browser_fallback = True" in _source(CRAWLER_PATH)


def test_rendered_dom_links_use_crawlee_native_discovery() -> None:
    crawler_source = _source(CRAWLER_PATH)
    rendering_source = _source(RENDERING_PATH)

    assert "extracted_requests = await context.extract_links(" in rendering_source
    assert "fallback_html, fallback_links = await render_url_with_crawlee(" in crawler_source
    assert "await fallback_context.enqueue_links(" in crawler_source
    assert "scope_pattern.search(candidate_url)" in crawler_source
    assert "EXCLUDED_URL_PATTERNS" in crawler_source


def test_invalid_rendered_links_are_skipped() -> None:
    source = _source(CRAWLER_PATH)

    assert "except (TypeError, ValueError):" in source
