"""Architecture contracts for native adaptive rendering."""

from pathlib import Path

ENGINE_PATH = Path("src/docsync/crawl_engine.py")


def test_native_adaptive_crawler_owns_http_to_browser_switching() -> None:
    source = ENGINE_PATH.read_text(encoding="utf-8")
    assert "AdaptivePlaywrightCrawler.with_beautifulsoup_static_parser(" in source
    assert "result_checker=adaptive_result_is_meaningful" in source
    assert "playwright_only=True" in source
    assert "PlaywrightFallbackRenderer" not in source
