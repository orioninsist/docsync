"""Regression tests for false language detection in ordinary subdomains."""

from __future__ import annotations

from bs4 import BeautifulSoup

from docsync.crawler import (
    build_scope_pattern,
    extract_in_scope_links,
)
from docsync.language import (
    detect_explicit_url_language,
    is_explicitly_non_english_url,
)


def test_arbitrary_language_code_like_subdomain_is_not_a_locale() -> None:
    url = "https://sw.kovidgoyal.net/kitty/"

    assert detect_explicit_url_language(url) is None
    assert is_explicitly_non_english_url(url) is False


def test_other_short_product_subdomains_are_not_languages() -> None:
    urls = [
        "https://go.example.com/docs/",
        "https://id.example.com/docs/",
        "https://io.example.com/docs/",
        "https://it.example.com/docs/",
        "https://no.example.com/docs/",
        "https://se.example.com/docs/",
    ]

    for url in urls:
        assert detect_explicit_url_language(url) is None
        assert is_explicitly_non_english_url(url) is False


def test_explicit_language_query_is_still_detected() -> None:
    decision = detect_explicit_url_language("https://example.com/docs/?lang=tr")

    assert decision is not None
    assert decision.is_english is False
    assert decision.language_code == "tr"
    assert decision.source == "url-query"


def test_explicit_language_path_is_still_detected() -> None:
    decision = detect_explicit_url_language("https://example.com/tr/docs/")

    assert decision is not None
    assert decision.is_english is False
    assert decision.language_code == "tr"
    assert decision.source == "url-path"


def test_intl_language_path_is_still_detected() -> None:
    decision = detect_explicit_url_language("https://example.com/intl/de/docs/")

    assert decision is not None
    assert decision.is_english is False
    assert decision.language_code == "de"
    assert decision.source == "url-intl-path"


def test_kitty_links_survive_english_url_filtering() -> None:
    base_url = "https://sw.kovidgoyal.net/kitty/"

    soup = BeautifulSoup(
        """
        <html>
          <body>
            <a href="overview/">Overview</a>
            <a href="conf/">Configuration</a>
            <a href="/kitty/actions/">Actions</a>
            <a href="https://sw.kovidgoyal.net/kitty/kittens/custom/">Custom</a>
          </body>
        </html>
        """,
        "lxml",
    )

    links = extract_in_scope_links(
        soup=soup,
        base_url=base_url,
        scope_pattern=build_scope_pattern(base_url),
    )

    assert links == [
        "https://sw.kovidgoyal.net/kitty/overview",
        "https://sw.kovidgoyal.net/kitty/conf",
        "https://sw.kovidgoyal.net/kitty/actions",
        "https://sw.kovidgoyal.net/kitty/kittens/custom",
    ]
