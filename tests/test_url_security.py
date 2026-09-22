from __future__ import annotations

import pytest

from docsync.url_security import (
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

