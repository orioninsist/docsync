"""Utilities for extracting crawlable links."""

from __future__ import annotations

from collections.abc import Callable

from bs4 import BeautifulSoup

from crawler.shared.url_policy import BLOCKED_SCHEMES

NormalizeUrl = Callable[[str], str | None]
BadUrlChecker = Callable[[str], str | None]

_SKIP_PREFIXES = (
    "#",
    *(f"{scheme}:" for scheme in BLOCKED_SCHEMES),
)


def _clean_attr_value(value: str | None) -> str | None:
    """Return a stripped attribute value when it is useful for crawling."""
    if not value:
        return None

    cleaned = value.strip()

    if not cleaned:
        return None

    return cleaned


def extract_links(
    html_links: list[str],
    *,
    normalize_url: NormalizeUrl,
    bad_url_checker: BadUrlChecker,
) -> list[str]:
    """Return normalized crawlable links."""
    results: list[str] = []

    for raw_link in html_links:
        cleaned = _clean_attr_value(raw_link)

        if not cleaned:
            continue

        if cleaned.startswith(_SKIP_PREFIXES):
            continue

        normalized = normalize_url(cleaned)

        if not normalized:
            continue

        if bad_url_checker(normalized):
            continue

        results.append(normalized)

    return results


def extract_real_urls_from_html(
    html: str,
    _base_url: str,
    *,
    normalize: NormalizeUrl,
) -> list[str]:
    """Extract normalized URLs from HTML content."""
    soup = BeautifulSoup(html, "html.parser")

    hrefs: list[str] = []

    for tag in soup.find_all("a", href=True):
        href = tag.get("href")

        if isinstance(href, str):
            hrefs.append(href)

    return extract_links(
        hrefs,
        normalize_url=normalize,
        bad_url_checker=lambda url: None,
    )


__all__ = [
    "extract_links",
    "extract_real_urls_from_html",
]
