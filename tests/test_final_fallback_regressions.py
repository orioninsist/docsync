"""Final regressions for sitemap failures and JavaScript-only fallback."""

from __future__ import annotations

import ast
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError

import pytest

from docsync.sitemap import SitemapDiscoveryResult, discover_sitemap_urls_sync

ROOT = Path(__file__).resolve().parents[1]
CRAWLER_PATH = ROOT / "src" / "docsync" / "crawler.py"
RUNTIME_PATH = ROOT / "src" / "docsync" / "crawler_runtime.py"
RENDERING_PATH = ROOT / "src" / "docsync" / "playwright_rendering.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tree(path: Path) -> ast.Module:
    return ast.parse(
        _source(path),
        filename=str(path),
    )


def test_sitemap_403_is_recorded_without_aborting_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_every_request(
        url: str,
        timeout_seconds: int,
    ) -> tuple[str, str]:
        del timeout_seconds

        raise HTTPError(
            url,
            403,
            "Forbidden",
            Message(),
            None,
        )

    monkeypatch.setattr(
        "docsync.sitemap.fetch_text_url",
        reject_every_request,
    )

    result = discover_sitemap_urls_sync(
        start_url="https://example.com/docs",
        timeout_seconds=10,
        max_urls=100,
    )

    assert isinstance(result, SitemapDiscoveryResult)
    assert result.urls == []
    assert result.sitemap_files_found == 0
    assert result.sitemap_files_checked == 3
    assert len(result.errors) == 4
    assert all("HTTPError" in error for error in result.errors)
    assert all("403" in error or "Forbidden" in error for error in result.errors)


def test_http_empty_markdown_triggers_playwright_renderer() -> None:
    source = _source(CRAWLER_PATH)

    assert 'resolved_mode != "http"' in source
    assert '"No meaningful Markdown content found:"' in source
    assert "fallback_html = await render_url_html(" in source
    assert "used_browser_fallback = True" in source


def test_javascript_only_fallback_reexports_rendered_dom() -> None:
    tree = _tree(CRAWLER_PATH)

    render_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "render_url_html"
    ]

    export_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "export"
    ]

    assert len(render_calls) == 1
    assert len(export_calls) >= 2


def test_rendered_dom_links_return_to_crawlee_queue() -> None:
    source = _source(CRAWLER_PATH)

    assert 'soup.select("a[href]")' in source
    assert "fallback_context.add_requests(" in source
    assert "scope_pattern.search(candidate_url)" in source
    assert "EXCLUDED_URL_PATTERNS" in source


def test_isolated_renderer_waits_for_javascript_and_returns_html() -> None:
    source = _source(RENDERING_PATH)

    assert "async def render_url_html(" in source
    assert 'wait_until="domcontentloaded"' in source
    assert '"networkidle"' in source
    assert "rendered_html: str = await page.content()" in source
    assert "await browser.close()" in source


def test_http_and_playwright_use_official_throttling_manager() -> None:
    crawler_source = _source(CRAWLER_PATH)
    runtime_source = _source(RUNTIME_PATH)

    assert "runtime = await build_crawlee_runtime(" in crawler_source
    assert crawler_source.count("request_manager=request_manager") == 2
    assert "request_manager = ThrottlingRequestManager(" in runtime_source
    assert "request_manager_opener=open_run_request_queue" in runtime_source
    assert 'alias="docsync-main"' in runtime_source
    assert "MemoryStorageClient" in runtime_source
    assert "request_manager_opener=RequestQueue.open" not in runtime_source
    assert "CrawlDelayThrottle(" not in crawler_source
    assert "await crawl_delay_throttle.wait()" not in crawler_source
