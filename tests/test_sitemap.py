from __future__ import annotations

from unittest.mock import MagicMock

from docsync.sitemap import build_sitemap_request_loader, sitemap_seed_urls


def test_sitemap_seeds_are_origin_rooted() -> None:
    assert sitemap_seed_urls("https://example.com/docs/start") == [
        "https://example.com/sitemap.xml",
        "https://example.com/sitemap_index.xml",
        "https://example.com/sitemap.txt",
        "https://example.com/sitemap.xml.gz",
    ]


def test_sitemap_loader_uses_crawlee_native_loader() -> None:
    loader = build_sitemap_request_loader(
        start_url="https://example.com/docs",
        http_client=MagicMock(),
    )
    assert type(loader).__name__ == "SitemapRequestLoader"
