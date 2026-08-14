"""Regression tests for redirect-aware relative-link resolution."""

from __future__ import annotations

from bs4 import BeautifulSoup

from docsync.crawler import (
    build_scope_pattern,
    extract_in_scope_links,
)


def test_directory_links_resolve_against_loaded_trailing_slash_url() -> None:
    requested_url = "https://example.com/docs"
    effective_url = "https://example.com/docs/"
    scope_pattern = build_scope_pattern(requested_url)

    soup = BeautifulSoup(
        """
        <html>
          <body>
            <a href="guide/">Guide</a>
            <a href="api/">API</a>
            <a href="./faq/">FAQ</a>
          </body>
        </html>
        """,
        "lxml",
    )

    links = extract_in_scope_links(
        soup=soup,
        base_url=effective_url,
        scope_pattern=scope_pattern,
    )

    assert links == [
        "https://example.com/docs/guide",
        "https://example.com/docs/api",
        "https://example.com/docs/faq",
    ]


def test_request_url_without_trailing_slash_would_resolve_incorrectly() -> None:
    requested_url = "https://example.com/docs"
    scope_pattern = build_scope_pattern(requested_url)

    soup = BeautifulSoup(
        '<a href="guide/">Guide</a>',
        "lxml",
    )

    links = extract_in_scope_links(
        soup=soup,
        base_url=requested_url,
        scope_pattern=scope_pattern,
    )

    assert links == []


def test_absolute_links_remain_supported_with_effective_url_base() -> None:
    scope_pattern = build_scope_pattern("https://example.com/docs")

    soup = BeautifulSoup(
        """
        <a href="https://example.com/docs/reference/">
          Reference
        </a>
        """,
        "lxml",
    )

    links = extract_in_scope_links(
        soup=soup,
        base_url="https://example.com/docs/",
        scope_pattern=scope_pattern,
    )

    assert links == [
        "https://example.com/docs/reference",
    ]
