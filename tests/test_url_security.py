from __future__ import annotations

from email.message import Message
from urllib.error import HTTPError

import pytest

from docsync.url_security import (
    SameOriginRedirectHandler,
    normalized_http_origin,
    validated_http_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/docs",
        "https://example.com/docs",
        "https://example.com:8443/docs",
        "https://subdomain.example.com/path?query=1",
    ],
)
def testvalidated_http_url_accepts_http_and_https(url: str) -> None:
    assert validated_http_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/archive",
        "javascript:alert(1)",
        "data:text/plain,unsafe",
        "//example.com/path",
        "https:///missing-host",
        "https://user:password@example.com/private",
        "https://example.com:invalid/path",
    ],
)
def testvalidated_http_url_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(ValueError):
        validated_http_url(url)


def testnormalized_http_origin_uses_default_ports() -> None:
    assert normalized_http_origin("http://EXAMPLE.com/path") == (
        "http",
        "example.com",
        80,
    )
    assert normalized_http_origin("https://EXAMPLE.com/path") == (
        "https",
        "example.com",
        443,
    )


def test_redirect_handler_accepts_same_origin_redirect() -> None:
    handler = SameOriginRedirectHandler("https://example.com/sitemap.xml")

    assert (
        handler.validate_redirect("https://example.com/other-sitemap.xml")
        == "https://example.com/other-sitemap.xml"
    )


@pytest.mark.parametrize(
    "redirect_url",
    [
        "https://attacker.example/sitemap.xml",
        "http://example.com/sitemap.xml",
        "https://example.com:8443/sitemap.xml",
    ],
)
def test_redirect_handler_rejects_cross_origin_redirects(
    redirect_url: str,
) -> None:
    handler = SameOriginRedirectHandler("https://example.com/sitemap.xml")

    with pytest.raises(
        HTTPError,
        match="Cross-origin redirect blocked",
    ):
        handler.validate_redirect(redirect_url)


def test_redirect_handler_rejects_non_http_redirect() -> None:
    handler = SameOriginRedirectHandler("https://example.com/sitemap.xml")

    with pytest.raises(
        ValueError,
        match="Only HTTP and HTTPS URLs are permitted",
    ):
        handler.validate_redirect("file:///etc/passwd")


def test_redirect_handler_rejects_cross_host_before_following() -> None:
    handler = SameOriginRedirectHandler("https://example.com/sitemap.xml")
    headers = Message()
    headers["Location"] = "https://attacker.example/sitemap.xml"

    with pytest.raises(HTTPError, match="Cross-origin redirect blocked"):
        handler.validate_redirect(headers["Location"])
