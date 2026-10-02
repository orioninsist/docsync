from __future__ import annotations

from pathlib import Path

from docsync.cli import build_parser
from docsync.policy import NORMALIZE_DOCUMENT, canonicalize_url


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
    assert "sitemap_sources.update(" in source
    assert "sitemap_urls=sorted(sitemap_sources)" in source
    assert "for url in common_sitemap.urls:" in source
    assert "Request.from_url(" in source
    assert "canonicalize_url(url)" in source


def test_discovered_sitemap_requests_use_throttled_request_manager() -> None:
    source = Path("src/docsync/crawler.py").read_text(encoding="utf-8")

    assert "await request_manager.add_request(request)" in source
    assert "await queue.add_request(request)" not in source


def test_canonicalize_url_removes_fragment_and_tracking_parameters() -> None:
    assert (
        canonicalize_url(
            "https://example.com/docs?page=2&utm_source=test&gclid=abc#section"
        )
        == "https://example.com/docs?page=2"
    )


def test_canonicalize_url_preserves_semantic_query_parameters() -> None:
    assert (
        canonicalize_url("https://example.com/docs?version=3&lang=en&page=2&filter=api")
        == "https://example.com/docs?version=3&lang=en&page=2&filter=api"
    )


def test_canonicalize_url_removes_case_insensitive_tracking_parameters() -> None:
    assert (
        canonicalize_url(
            "https://example.com/docs?UTM_Medium=email&FbClId=abc&topic=crawl"
        )
        == "https://example.com/docs?topic=crawl"
    )


def test_url_transform_is_used_for_links_and_sitemaps() -> None:
    source = Path("src/docsync/crawler.py").read_text(encoding="utf-8")

    assert "transform_request_function=transform_request" in source
    assert source.count("transform_request_function=transform_request") == 2


def test_optional_sitemap_discovery_errors_are_observable() -> None:
    python_source = Path("src/docsync/crawler.py").read_text(encoding="utf-8")
    typescript_source = Path("typescript/src/index.ts").read_text(encoding="utf-8")

    assert "suppress(Exception)" not in python_source
    assert "Unable to discover sitemaps from robots.txt" in python_source
    assert "Unable to load declared sitemaps" in python_source
    assert "Unable to discover common sitemaps" in python_source

    assert "catch {}" not in typescript_source
    assert "Unable to discover sitemaps from robots.txt" in typescript_source
    assert "Unable to discover common sitemaps" in typescript_source
