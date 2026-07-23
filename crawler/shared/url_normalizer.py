"""URL normalization helpers."""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from crawler.shared.language_policy import (
    NORMALIZED_ENGLISH_QUERY_VALUES,
    is_english_language_value,
)
from crawler.shared.url_policy import BLOCKED_SCHEMES


def normalize_url(url: str) -> str | None:
    """Normalize URL for crawler storage and comparison."""
    parsed = urlparse(url.strip())

    if not parsed.scheme or not parsed.netloc:
        return None

    scheme = parsed.scheme.lower()

    if scheme not in {"http", "https"}:
        return None

    if scheme in BLOCKED_SCHEMES:
        return None

    normalized_query = _normalize_query(parsed.query)

    return urlunparse(
        (
            scheme,
            parsed.netloc.lower(),
            parsed.path or "/",
            "",
            normalized_query,
            "",
        )
    )


def normalize_optional_url(url: str) -> str | None:
    """Normalize optional URL values safely."""
    try:
        return normalize_url(url)
    except ValueError:
        return None


def url_sha256(url: str) -> str:
    """Return SHA256 hash of normalized URL."""
    normalized = normalize_url(url)

    if normalized is None:
        normalized = url.strip()

    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalize_query(query: str) -> str:
    """Normalize query parameters."""
    values = parse_qsl(query, keep_blank_values=True)

    normalized: list[tuple[str, str]] = []

    for key, value in values:
        normalized.append(
            (
                key.lower().strip(),
                value.strip(),
            )
        )

    return urlencode(normalized)


def is_english_url(url: str) -> bool:
    """Return whether URL query values indicate English."""
    parsed = urlparse(url)

    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        if key.lower().strip() in {
            "lang",
            "language",
            "locale",
            "hl",
        }:
            if value.lower() in NORMALIZED_ENGLISH_QUERY_VALUES:
                return True

            if is_english_language_value(value):
                return True

    return False


def normalize_joined_url(base_url: str, candidate_url: str) -> str | None:
    """Join candidate URL with base URL and return normalized result."""
    from urllib.parse import urldefrag, urljoin

    raw_candidate = candidate_url.strip()

    if not raw_candidate:
        return None

    joined = urljoin(base_url, raw_candidate)
    clean_url, _fragment = urldefrag(joined)

    return normalize_url(clean_url)


