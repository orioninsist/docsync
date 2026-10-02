from __future__ import annotations

from pathlib import Path

from docsync.cli import build_parser
from docsync.policy import NORMALIZE_DOCUMENT


def test_web_crawl_defaults_are_unlimited_and_sitemap_enabled() -> None:
    args = build_parser().parse_args(["sync", "https://example.com/docs"])
    assert args.max_requests is None
    assert args.crawl_strategy == "same-origin"
    assert args.no_sitemap is False


def test_web_crawl_can_set_explicit_limit_scope_and_disable_sitemap() -> None:
    args = build_parser().parse_args(
        [
            "sync",
            "https://example.com/docs",
            "--max-requests",
            "250",
            "--crawl-strategy",
            "same-domain",
            "--no-sitemap",
        ]
    )
    assert args.max_requests == 250
    assert args.crawl_strategy == "same-domain"
    assert args.no_sitemap is True


def test_document_normalizer_preserves_semantic_asides_and_role_buttons() -> None:
    assert "nav,aside" not in NORMALIZE_DOCUMENT
    assert '[role="button"]' not in NORMALIZE_DOCUMENT


def test_sitemap_requests_use_crawler_request_manager() -> None:
    source = (
        __import__("pathlib").Path("src/docsync/crawler.py").read_text(encoding="utf-8")
    )
    assert "await request_manager.add_request(request)" in source
    assert "await queue.add_request(request)" not in source


def test_crawl_completion_uses_crawler_request_manager() -> None:
    source = (
        __import__("pathlib").Path("src/docsync/crawler.py").read_text(encoding="utf-8")
    )
    assert "await request_manager.is_finished()" in source
    assert "await queue.is_finished()" not in source


def test_python_sitemap_discovery_matches_expected_sources() -> None:
    source = Path("src/docsync/crawler.py").read_text(encoding="utf-8")

    assert "RobotsTxtFile.find(start_url, http_client)" in source
    assert "robots.get_sitemaps(enqueue_strategy=crawl_strategy)" in source
    assert "Sitemap.try_common_names(origin, http_client)" in source
    assert "sitemap_urls.update(common_sitemap.urls)" in source
    assert "sitemap_urls=sorted(sitemap_urls)" in source


def test_discovered_sitemap_requests_use_throttled_request_manager() -> None:
    source = Path("src/docsync/crawler.py").read_text(encoding="utf-8")

    assert "await request_manager.add_request(request)" in source
    assert "await queue.add_request(request)" not in source
