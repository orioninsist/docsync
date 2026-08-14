"""Regression tests for the permanent English-only URL policy."""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from docsync.crawler import (
    build_scope_pattern,
    extract_in_scope_links,
)
from docsync.language import (
    detect_explicit_url_language,
    is_explicitly_non_english_url,
)
from docsync.sitemap import (
    SitemapDiscoveryResult,
    discover_sitemap_urls_sync,
)

ROOT = Path(__file__).resolve().parents[1]
CRAWLER_PATH = ROOT / "src/docsync/crawler.py"


@pytest.mark.parametrize(
    "url",
    [
        "https://developers.google.com/?hl=de",
        "https://developers.google.com/docs?hl=fr",
        "https://developers.google.com/docs?locale=ja",
        "https://developers.google.com/docs?lang=tr",
        "https://developers.google.com/intl/ko/docs",
        "https://developers.google.com/fr/docs",
        "https://ja.developers.google.com/docs",
    ],
)
def test_explicit_non_english_google_urls_are_rejected(url: str) -> None:
    assert is_explicitly_non_english_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://developers.google.com/",
        "https://developers.google.com/docs",
        "https://developers.google.com/docs?hl=en",
        "https://developers.google.com/intl/en/docs",
        "https://en.developers.google.com/docs",
    ],
)
def test_english_google_urls_are_allowed(url: str) -> None:
    assert is_explicitly_non_english_url(url) is False


def test_url_language_decision_records_query_source() -> None:
    decision = detect_explicit_url_language("https://developers.google.com/docs?hl=ja")

    assert decision is not None
    assert decision.is_english is False
    assert decision.language_code == "ja"
    assert decision.source == "url-query"


def test_html_discovery_only_returns_english_urls() -> None:
    soup = BeautifulSoup(
        """
        <html lang="en">
          <body>
            <a href="/docs/english">English</a>
            <a href="/docs/german?hl=de">German</a>
            <a href="/intl/ja/docs/japanese">Japanese</a>
            <a href="/fr/docs/french">French</a>
          </body>
        </html>
        """,
        "html.parser",
    )

    scope_pattern = build_scope_pattern("https://developers.google.com")

    assert extract_in_scope_links(
        soup=soup,
        base_url="https://developers.google.com",
        scope_pattern=scope_pattern,
    ) == [
        "https://developers.google.com/docs/english",
    ]


def test_http_and_playwright_use_the_same_filtered_url_list() -> None:
    source = CRAWLER_PATH.read_text(encoding="utf-8")

    assert "await context.enqueue_links(" not in source
    assert "await queue_context.add_requests(" in source
    assert "await fallback_context.add_requests(" in source
    assert "is_explicitly_non_english_url(candidate_url)" in source


def test_sitemap_discovery_filters_localized_page_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = {
        "https://developers.google.com/robots.txt": (
            "https://developers.google.com/robots.txt",
            "",
        ),
        "https://developers.google.com/sitemap.xml": (
            "https://developers.google.com/sitemap.xml",
            """
            <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url>
                <loc>https://developers.google.com/docs/english</loc>
              </url>
              <url>
                <loc>https://developers.google.com/docs/german?hl=de</loc>
              </url>
              <url>
                <loc>https://developers.google.com/intl/ja/docs</loc>
              </url>
            </urlset>
            """,
        ),
    }

    def fake_fetch(
        url: str,
        timeout_seconds: int,
    ) -> tuple[str, str]:
        del timeout_seconds

        if url in responses:
            return responses[url]

        raise ValueError("missing sitemap")

    monkeypatch.setattr(
        "docsync.sitemap.fetch_text_url",
        fake_fetch,
    )

    result = discover_sitemap_urls_sync(
        start_url="https://developers.google.com",
        timeout_seconds=5,
        max_urls=100,
    )

    assert isinstance(result, SitemapDiscoveryResult)
    assert result.urls == [
        "https://developers.google.com/docs/english",
    ]
