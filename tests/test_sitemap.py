from __future__ import annotations

import gzip
from email.message import Message
from io import BytesIO
from urllib.error import HTTPError

import pytest

from docsync.sitemap import (
    SITEMAP_MAX_PAYLOAD_BYTES,
    SitemapDiscoveryResult,
    decode_sitemap_payload,
    extract_robots_sitemaps,
    fetch_text_url,
    sitemap_candidate_urls,
    sitemap_xml_locations,
)


class FakeResponse:
    def __init__(
        self,
        *,
        url: str,
        payload: bytes,
    ) -> None:
        self._url = url
        self._stream = BytesIO(payload)

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(
        self,
        exc_type: object,
        exc: object,
        traceback: object,
    ) -> None:
        return None

    def geturl(self) -> str:
        return self._url

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)


def test_sitemap_result_defaults() -> None:
    result = SitemapDiscoveryResult()

    assert result.urls == []
    assert result.sitemap_files_checked == 0
    assert result.sitemap_files_found == 0
    assert result.errors == []


def test_decode_sitemap_payload_decodes_plain_xml() -> None:
    payload = b'<?xml version="1.0"?><urlset></urlset>'

    assert decode_sitemap_payload(
        payload,
        "https://example.com/sitemap.xml",
    ) == payload.decode("utf-8")


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/sitemap.xml.gz",
        "https://example.com/sitemap.xml",
    ],
)
def test_decode_sitemap_payload_decompresses_gzip(
    url: str,
) -> None:
    expected = '<?xml version="1.0"?><urlset></urlset>'
    payload = gzip.compress(expected.encode("utf-8"))

    assert (
        decode_sitemap_payload(
            payload,
            url,
        )
        == expected
    )


def test_extract_robots_sitemaps() -> None:
    robots_text = """
    User-agent: *
    Disallow: /private

    Sitemap: /sitemap.xml
    sitemap: https://example.com/sitemap-news.xml # comment
    Sitemap: /sitemap.xml
    Sitemap:
    """

    assert extract_robots_sitemaps(
        robots_text,
        "https://example.com/",
    ) == [
        "https://example.com/sitemap.xml",
        "https://example.com/sitemap-news.xml",
    ]


@pytest.mark.parametrize(
    (
        "xml_text",
        "expected_type",
        "expected_locations",
    ),
    [
        (
            (
                '<?xml version="1.0"?>'
                '<urlset xmlns="http://www.sitemaps.org/'
                'schemas/sitemap/0.9">'
                "<url><loc>https://example.com/a</loc></url>"
                "</urlset>"
            ),
            "urlset",
            ["https://example.com/a"],
        ),
        (
            (
                '<?xml version="1.0"?>'
                '<sitemapindex xmlns="http://www.sitemaps.org/'
                'schemas/sitemap/0.9">'
                "<sitemap>"
                "<loc>https://example.com/sitemap-a.xml</loc>"
                "</sitemap>"
                "</sitemapindex>"
            ),
            "index",
            ["https://example.com/sitemap-a.xml"],
        ),
    ],
)
def test_sitemap_xml_locations(
    xml_text: str,
    expected_type: str,
    expected_locations: list[str],
) -> None:
    sitemap_type, locations = sitemap_xml_locations(xml_text)

    assert sitemap_type == expected_type
    assert locations == expected_locations


def test_sitemap_xml_locations_rejects_unknown_root() -> None:
    with pytest.raises(
        ValueError,
        match="Unsupported sitemap root element",
    ):
        sitemap_xml_locations("<feed></feed>")


def test_sitemap_candidates_are_origin_rooted() -> None:
    assert sitemap_candidate_urls("https://example.com/docs/start") == [
        "https://example.com/sitemap.xml",
        "https://example.com/sitemap_index.xml",
        "https://example.com/sitemap.xml.gz",
    ]


def test_fetch_text_url_enforces_payload_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oversized = b"x" * (SITEMAP_MAX_PAYLOAD_BYTES + 1)

    monkeypatch.setattr(
        "docsync.sitemap.secure_urlopen",
        lambda *args, **kwargs: FakeResponse(
            url="https://example.com/sitemap.xml",
            payload=oversized,
        ),
    )

    with pytest.raises(
        ValueError,
        match="20 MiB sitemap safety limit",
    ):
        fetch_text_url(
            "https://example.com/sitemap.xml",
            10,
        )


def test_fetch_text_url_uses_final_same_origin_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"<urlset></urlset>"

    monkeypatch.setattr(
        "docsync.sitemap.secure_urlopen",
        lambda *args, **kwargs: FakeResponse(
            url="https://example.com/final-sitemap.xml",
            payload=payload,
        ),
    )

    final_url, text = fetch_text_url(
        "https://example.com/sitemap.xml",
        10,
    )

    assert final_url == "https://example.com/final-sitemap.xml"
    assert text == payload.decode("utf-8")


def test_fetch_text_url_propagates_redirect_security(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_redirect_error(
        *args: object,
        **kwargs: object,
    ) -> object:
        raise HTTPError(
            "https://attacker.example/sitemap.xml",
            403,
            "Cross-origin redirect blocked",
            Message(),
            None,
        )

    monkeypatch.setattr(
        "docsync.sitemap.secure_urlopen",
        raise_redirect_error,
    )

    with pytest.raises(
        HTTPError,
        match="Cross-origin redirect blocked",
    ):
        fetch_text_url(
            "https://example.com/sitemap.xml",
            10,
        )
