"""Pure sitemap language selection helpers."""

from __future__ import annotations

from html import unescape
from typing import Any
from urllib.parse import parse_qs, urlparse

from crawler.shared.language_policy import (
    ENGLISH_PATH_HINTS,
    LANGUAGE_QUERY_KEYS,
    NON_ENGLISH_PATH_HINTS,
    NORMALIZED_ENGLISH_QUERY_VALUES,
)


def english_candidates_from_sitemap_url_node(
    *,
    url_node: Any,
    fallback_url: str,
    require_english: bool,
    strip_namespace: Any,
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

    if has_language_alternates or url_declares_non_english(fallback_url):
        return set()

    return {fallback_url}


def english_alternates(
    url_node: Any,
    *,
    strip_namespace: Any,
) -> tuple[set[str], bool]:
    """Return English alternate hrefs and whether language alternates exist."""

    alternate_urls: set[str] = set()
    has_language_alternates = False

    for child in url_node.iter():
        if strip_namespace(child.tag).lower() != "link":
            continue

        href = english_alternate_href(child)

        if href is None:
            has_language_alternates = is_alternate_link(child)
            continue

        has_language_alternates = True
        alternate_urls.add(href)

    return alternate_urls, has_language_alternates


def english_alternate_href(child: Any) -> str | None:
    """Return href when an alternate sitemap link targets English."""

    if not is_alternate_link(child):
        return None

    hreflang = str(child.attrib.get("hreflang", "")).strip().lower()
    href = str(child.attrib.get("href", "")).strip()

    if hreflang_is_english(hreflang) and href:
        return unescape(href)

    return None


def is_alternate_link(child: Any) -> bool:
    """Return True for sitemap alternate language links."""

    rel = str(child.attrib.get("rel", "")).strip().lower()
    hreflang = str(child.attrib.get("hreflang", "")).strip().lower()

    return rel == "alternate" and bool(hreflang)


def url_declares_non_english(url: str) -> bool:
    """Return True when path or query declares a non-English language."""

    parsed = urlparse(url)

    return path_contains_non_english_language_segment(
        parsed.path.lower(),
    ) or query_declares_non_english(parsed.query)


def query_declares_non_english(query: str) -> bool:
    """Return True when language query parameters are explicitly non-English."""

    parsed_query = parse_qs(query)

    for key, values in parsed_query.items():
        if key.lower() not in LANGUAGE_QUERY_KEYS:
            continue

        if values_declare_non_english(values):
            return True

    return False


def values_declare_non_english(values: list[str]) -> bool:
    """Return True when any query value is non-empty and not English."""

    return any(
        (value_lower := value.strip().lower().replace("_", "-"))
        and value_lower not in NORMALIZED_ENGLISH_QUERY_VALUES
        for value in values
    )


def path_contains_non_english_language_segment(path: str) -> bool:
    """Return True when URL path has a non-English language marker."""

    normalized_path = f"/{path.lower().strip('/')}/"

    if any(hint in normalized_path for hint in ENGLISH_PATH_HINTS):
        return False

    return any(hint in normalized_path for hint in NON_ENGLISH_PATH_HINTS)


def hreflang_is_english(hreflang: str) -> bool:
    """Return True when hreflang explicitly targets English."""

    normalized = hreflang.strip().lower().replace("_", "-")

    return normalized in NORMALIZED_ENGLISH_QUERY_VALUES or normalized.startswith("en-")
