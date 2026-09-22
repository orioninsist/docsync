"""Native adaptive HTTP-to-Playwright fallback contracts."""

from pathlib import Path

ENGINE = Path("src/docsync/crawl_engine.py")
CRAWLER = Path("src/docsync/crawler.py")
RENDERING = Path("src/docsync/playwright_rendering.py")


def test_http_mode_uses_native_adaptive_crawler() -> None:
    source = ENGINE.read_text(encoding="utf-8")
    assert "AdaptivePlaywrightCrawler.with_beautifulsoup_static_parser(" in source
    assert "result_checker=adaptive_result_is_meaningful" in source


def test_empty_content_is_an_adaptive_rejection_marker() -> None:
    source = CRAWLER.read_text(encoding="utf-8")
    assert '"outcome": "empty"' in source
    assert '"No meaningful Markdown content found:"' in source


def test_selected_renderer_uses_one_markdown_export_path() -> None:
    source = CRAWLER.read_text(encoding="utf-8")
    assert source.count("document = markdown_exporter.export(") == 1
    assert "await context.push_data(" in source


def test_rendered_links_use_the_same_native_discovery_path() -> None:
    source = CRAWLER.read_text(encoding="utf-8")
    assert "await context.extract_links(" in source
    assert "await context.enqueue_links(" in source


def test_custom_fallback_renderer_is_removed() -> None:
    source = RENDERING.read_text(encoding="utf-8")
    assert "PlaywrightFallbackRenderer" not in source
    assert "render_url_with_crawlee" not in source
    assert "asyncio.create_task(crawler.run())" not in source
