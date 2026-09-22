"""Regressions for sitemap failures and native adaptive rendering."""

from email.message import Message
from pathlib import Path
from urllib.error import HTTPError

import pytest

from docsync.sitemap import SitemapDiscoveryResult, discover_sitemap_urls_sync

ROOT = Path(__file__).resolve().parents[1]
CRAWLER = ROOT / "src/docsync/crawler.py"
ENGINE = ROOT / "src/docsync/crawl_engine.py"
RUNTIME = ROOT / "src/docsync/crawler_runtime.py"
RENDERING = ROOT / "src/docsync/playwright_rendering.py"


def test_sitemap_403_is_recorded_without_aborting_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject_every_request(url: str, timeout_seconds: int) -> tuple[str, str]:
        del timeout_seconds
        raise HTTPError(url, 403, "Forbidden", Message(), None)

    monkeypatch.setattr("docsync.sitemap.fetch_text_url", reject_every_request)
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


def test_http_mode_uses_native_adaptive_fallback() -> None:
    source = ENGINE.read_text(encoding="utf-8")
    assert "AdaptivePlaywrightCrawler.with_beautifulsoup_static_parser(" in source
    assert "result_checker=adaptive_result_is_meaningful" in source


def test_browser_and_static_share_one_handler_and_discovery_path() -> None:
    source = CRAWLER.read_text(encoding="utf-8")
    assert source.count("@crawler.router.default_handler") == 1
    assert source.count("document = markdown_exporter.export(") == 1
    assert "discover_and_enqueue_in_scope_links(" in source


def test_browser_controls_use_adaptive_playwright_hook() -> None:
    source = ENGINE.read_text(encoding="utf-8")
    assert "playwright_only=True" in source
    assert "install_resource_blocking(" in source


def test_custom_renderer_lifecycle_is_gone() -> None:
    source = RENDERING.read_text(encoding="utf-8")
    assert "PlaywrightFallbackRenderer" not in source
    assert "MemoryStorageClient" not in source
    assert "asyncio.create_task" not in source


def test_http_and_playwright_use_official_throttling_manager() -> None:
    crawler_source = CRAWLER.read_text(encoding="utf-8")
    runtime_source = RUNTIME.read_text(encoding="utf-8")
    engine_source = ENGINE.read_text(encoding="utf-8")
    assert "runtime = await build_crawlee_runtime(" in crawler_source
    assert '"request_manager": runtime.request_manager' in engine_source
    assert "request_manager=runtime.request_manager" in engine_source
    assert "request_manager = ThrottlingRequestManager(" in runtime_source
    assert "request_manager_opener=RequestQueue.open" in runtime_source
    assert 'name="docsync-main"' in runtime_source
    assert "FileSystemStorageClient" in runtime_source
    assert "MemoryStorageClient" not in runtime_source
