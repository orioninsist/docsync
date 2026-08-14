"""Regression tests for sitemap response validation."""

from __future__ import annotations

import gzip

import pytest

from docsync.sitemap import (
    SitemapCompressionError,
    SitemapHtmlResponseError,
    SitemapResponseError,
    SitemapXmlError,
    decode_sitemap_payload,
    sitemap_xml_locations,
)


def test_html_sitemap_response_is_classified() -> None:
    payload = b"""<!doctype html>
    <html>
    <head><title>Access denied</title></head>
    <body>Blocked</body>
    </html>
    """

    with pytest.raises(
        SitemapHtmlResponseError,
        match="returned HTML",
    ):
        decode_sitemap_payload(
            payload,
            "https://example.com/sitemap.xml",
        )


def test_dot_gz_url_rejects_plain_html() -> None:
    payload = b"<!doctype html><html><body>Login</body></html>"

    with pytest.raises(SitemapHtmlResponseError):
        decode_sitemap_payload(
            payload,
            "https://example.com/sitemap.xml.gz",
        )


def test_dot_gz_url_rejects_non_gzip_xml() -> None:
    payload = b'<?xml version="1.0"?><urlset></urlset>'

    with pytest.raises(
        SitemapCompressionError,
        match="not gzip-compressed",
    ):
        decode_sitemap_payload(
            payload,
            "https://example.com/sitemap.xml.gz",
        )


def test_invalid_gzip_payload_is_classified() -> None:
    payload = b"\x1f\x8bnot-a-valid-gzip-stream"

    with pytest.raises(
        SitemapCompressionError,
        match="Invalid gzip sitemap response",
    ):
        decode_sitemap_payload(
            payload,
            "https://example.com/sitemap.xml",
        )


def test_valid_gzip_payload_still_decodes() -> None:
    expected = '<?xml version="1.0"?><urlset></urlset>'
    payload = gzip.compress(expected.encode("utf-8"))

    assert (
        decode_sitemap_payload(
            payload,
            "https://example.com/sitemap.xml.gz",
        )
        == expected
    )


def test_empty_sitemap_response_is_rejected() -> None:
    with pytest.raises(
        SitemapResponseError,
        match="Empty sitemap response",
    ):
        decode_sitemap_payload(
            b"   ",
            "https://example.com/sitemap.xml",
        )


def test_html_text_is_rejected_before_xml_parsing() -> None:
    with pytest.raises(
        SitemapHtmlResponseError,
        match="HTML instead of XML",
    ):
        sitemap_xml_locations("<html><body>Challenge</body></html>")


def test_malformed_xml_is_classified() -> None:
    with pytest.raises(
        SitemapXmlError,
        match="Malformed sitemap XML",
    ):
        sitemap_xml_locations("<urlset><url><loc>https://example.com/a</loc>")


def test_unsupported_xml_root_is_classified() -> None:
    with pytest.raises(
        SitemapXmlError,
        match="Unsupported sitemap root element",
    ):
        sitemap_xml_locations("<feed></feed>")
