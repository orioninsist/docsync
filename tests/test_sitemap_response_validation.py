"""Architecture regression tests for native sitemap handling."""

from pathlib import Path

SITEMAP = Path("src/docsync/sitemap.py")


def test_docsync_does_not_parse_or_decompress_sitemaps() -> None:
    source = SITEMAP.read_text(encoding="utf-8")
    assert "ElementTree" not in source
    assert "zlib" not in source
    assert "gzip" not in source
    assert "secure_urlopen" not in source


def test_docsync_uses_public_crawlee_sitemap_loader() -> None:
    source = SITEMAP.read_text(encoding="utf-8")
    assert "from crawlee.request_loaders import SitemapRequestLoader" in source
    assert "return SitemapRequestLoader(" in source
