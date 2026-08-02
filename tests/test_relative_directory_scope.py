from __future__ import annotations

from bs4 import BeautifulSoup

from docsync.crawler import (
    build_scope_pattern,
    extract_in_scope_links,
)


def test_directory_seed_preserves_relative_link_directory() -> None:
    base_url = "https://docs.python.org/3/"
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <a href="library/index.html">Library</a>
            <a href="reference/index.html">Reference</a>
          </body>
        </html>
        """,
        "lxml",
    )

    result = extract_in_scope_links(
        soup=soup,
        base_url=base_url,
        scope_pattern=build_scope_pattern(base_url),
    )

    assert result == [
        "https://docs.python.org/3/library/index.html",
        "https://docs.python.org/3/reference/index.html",
    ]


def test_nested_directory_parent_link_is_resolved_correctly() -> None:
    base_url = "https://example.com/docs/guide/"
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <a href="../getting-started.html">Getting started</a>
          </body>
        </html>
        """,
        "lxml",
    )

    result = extract_in_scope_links(
        soup=soup,
        base_url=base_url,
        scope_pattern=build_scope_pattern("https://example.com/docs/"),
    )

    assert result == [
        "https://example.com/docs/getting-started.html",
    ]


def test_file_page_relative_link_behavior_is_unchanged() -> None:
    base_url = "https://example.com/docs/index.html"
    soup = BeautifulSoup(
        """
        <html>
          <body>
            <a href="child.html">Child</a>
          </body>
        </html>
        """,
        "lxml",
    )

    result = extract_in_scope_links(
        soup=soup,
        base_url=base_url,
        scope_pattern=build_scope_pattern("https://example.com/docs/"),
    )

    assert result == [
        "https://example.com/docs/child.html",
    ]
