from __future__ import annotations

from pathlib import Path

CRAWLER_PATH = Path("src/docsync/crawler.py")
ENGINE_PATH = Path("src/docsync/crawl_engine.py")


def test_canonical_crawler_preserves_both_dispatch_targets() -> None:
    source = ENGINE_PATH.read_text(encoding="utf-8")
    assert "BeautifulSoupCrawler(" in source
    assert "PlaywrightCrawler(" in source


def test_canonical_crawler_dispatch_is_shared() -> None:
    crawler_source = CRAWLER_PATH.read_text(encoding="utf-8")
    engine_source = ENGINE_PATH.read_text(encoding="utf-8")
    assert "crawler_build = build_crawler(" in crawler_source
    assert 'if mode == "playwright":' in engine_source
    assert 'if mode == "http":' in engine_source


def test_playwright_crawler_is_owned_by_shared_engine() -> None:
    source = ENGINE_PATH.read_text(encoding="utf-8")
    assert "PlaywrightCrawler" in source
