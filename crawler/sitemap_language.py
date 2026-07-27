"""Pure sitemap language selection helpers."""

from __future__ import annotations

from collections.abc import Callable
from html import unescape
from xml.etree.ElementTree import Element

from crawler.shared.language_policy import NORMALIZED_ENGLISH_QUERY_VALUES


def english_candidates_from_sitemap_url_node(
    *,
    url_node: Element,
    fallback_url: str,
    require_english: bool,
    strip_namespace: Callable[[str], str],
) -> set[str]:
    """Return sitemap URL candidates after English alternate selection."""

    if not require_english:
        return {fallback_url}

    alternate_urls, has_language_alternates = english_alternates(
        url_node,
        strip_namespace=strip_namespace,
    )

    if alternate_urls:
        return alternate_urls

    if has_language_alternates:
        return set()

    return {fallback_url}


def english_alternates(
    url_node: Element,
    *,
    strip_namespace: Callable[[str], str],
) -> tuple[set[str], bool]:
    """Return English alternate hrefs and whether language alternates exist."""

    alternate_urls: set[str] = set()
    has_language_alternates = False

    for child in url_node.iter():
        if strip_namespace(child.tag).lower() != "link":
            continue

        href = english_alternate_href(child)

        if href is None:
            has_language_alternates = has_language_alternates or is_alternate_link(
                child
            )
            continue

        has_language_alternates = True
        alternate_urls.add(href)

    return alternate_urls, has_language_alternates


def english_alternate_href(child: Element) -> str | None:
    """Return href when an alternate sitemap link targets English."""

    if not is_alternate_link(child):
        return None

    hreflang = child.attrib.get("hreflang", "").strip().lower()
    href = child.attrib.get("href", "").strip()

    if hreflang_is_english(hreflang) and href:
        return unescape(href)

    return None


def is_alternate_link(child: Element) -> bool:
    """Return True for sitemap alternate language links."""

    rel = child.attrib.get("rel", "").strip().lower()
    hreflang = child.attrib.get("hreflang", "").strip().lower()

    return rel == "alternate" and bool(hreflang)


def hreflang_is_english(hreflang: str) -> bool:
    """Return True when hreflang explicitly targets English."""

    normalized = hreflang.strip().lower().replace("_", "-")

    return normalized in NORMALIZED_ENGLISH_QUERY_VALUES or normalized.startswith("en-")
