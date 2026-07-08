"""HTML discovery link extraction helpers."""

from __future__ import annotations

import re
from collections.abc import Callable
from html import unescape
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from bs4.element import Tag

NormalizeUrl = Callable[[str], str | None]
BadUrlChecker = Callable[[str], str | None]

_SKIP_PREFIXES = (
    "#",
    "mailto:",
    "tel:",
    "javascript:",
    "data:",
    "blob:",
    "file:",
    "ftp:",
)


def _clean_attr_value(value: str | None) -> str | None:
    """Return a stripped attribute value when it is useful for crawling."""
    clean = (value or "").strip()
    if not clean:
        return None
    if clean.lower().startswith(_SKIP_PREFIXES):
        return None
    return clean


def _normalized_joined_url(
    value: str,
    *,
    base_url: str,
    normalize: NormalizeUrl,
) -> str | None:
    """Join a candidate URL with the page URL and normalize it safely."""
    try:
        return normalize(urljoin(base_url, unescape(value)))
    except (TypeError, ValueError):
        return None


def _append_candidate(
    urls: list[str],
    value: str | None,
    *,
    base_url: str,
    normalize: NormalizeUrl,
) -> None:
    """Append a normalized candidate URL when it passes lightweight checks."""
    clean_value = _clean_attr_value(value)
    if clean_value is None:
        return

    clean_url = _normalized_joined_url(
        clean_value,
        base_url=base_url,
        normalize=normalize,
    )
    if clean_url:
        urls.append(clean_url)


def _tag_attr(tag: Tag, attr_name: str) -> str | None:
    """Read a string attribute from a BeautifulSoup tag."""
    value = tag.get(attr_name)
    if isinstance(value, str):
        return value
    return None


def _append_standard_tag_url(
    urls: list[str],
    tag: Tag,
    *,
    base_url: str,
    normalize: NormalizeUrl,
) -> None:
    """Append URL candidates from common link-bearing HTML tags."""
    if tag.name in {"a", "link", "area"}:
        _append_candidate(
            urls,
            _tag_attr(tag, "href"),
            base_url=base_url,
            normalize=normalize,
        )
        return

    if tag.name in {"script", "img", "iframe", "source", "video", "audio"}:
        _append_candidate(
            urls,
            _tag_attr(tag, "src"),
            base_url=base_url,
            normalize=normalize,
        )


def _append_meta_url(
    urls: list[str],
    tag: Tag,
    *,
    base_url: str,
    normalize: NormalizeUrl,
) -> None:
    """Append URL candidates from metadata tags."""
    if tag.name != "meta":
        return

    property_value = (_tag_attr(tag, "property") or "").lower()
    name_value = (_tag_attr(tag, "name") or "").lower()
    if property_value == "og:url" or name_value in {"twitter:url", "url"}:
        _append_candidate(
            urls,
            _tag_attr(tag, "content"),
            base_url=base_url,
            normalize=normalize,
        )


def _append_srcset_urls(
    urls: list[str],
    tag: Tag,
    *,
    base_url: str,
    normalize: NormalizeUrl,
) -> None:
    """Append URL candidates from srcset attributes."""
    srcset = _tag_attr(tag, "srcset")
    if not srcset:
        return

    for item in srcset.split(","):
        candidate = item.strip().split(" ", maxsplit=1)[0]
        _append_candidate(
            urls,
            candidate,
            base_url=base_url,
            normalize=normalize,
        )


def _append_inline_markdown_urls(
    urls: list[str],
    html: str,
    *,
    base_url: str,
    normalize: NormalizeUrl,
) -> None:
    """Append URL-like values embedded in inline markdown fragments."""
    for match in re.finditer(r"\]\(([^)]+)\)", html):
        _append_candidate(
            urls,
            match.group(1),
            base_url=base_url,
            normalize=normalize,
        )


def extract_real_urls_from_html(
    html: str,
    base_url: str,
    normalize: NormalizeUrl,
) -> list[str]:
    """Extract normalized URL candidates from HTML without filtering scope."""
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []

    for tag in soup.find_all(True):
        if not isinstance(tag, Tag):
            continue

        _append_standard_tag_url(
            urls,
            tag,
            base_url=base_url,
            normalize=normalize,
        )
        _append_meta_url(
            urls,
            tag,
            base_url=base_url,
            normalize=normalize,
        )
        _append_srcset_urls(
            urls,
            tag,
            base_url=base_url,
            normalize=normalize,
        )

    _append_inline_markdown_urls(
        urls,
        html,
        base_url=base_url,
        normalize=normalize,
    )

    return sorted(set(urls))


def extract_recursive_links(
    html: str,
    base_url: str,
    normalize: NormalizeUrl,
    is_bad_url: BadUrlChecker,
) -> list[str]:
    """Extract normalized recursive links after bad URL filtering."""
    links: list[str] = []

    for url in extract_real_urls_from_html(html, base_url, normalize):
        if is_bad_url(url):
            continue
        links.append(url)

    return sorted(set(links))
