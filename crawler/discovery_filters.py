"""Discovery filtering helpers."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlparse

from crawler.shared.url_policy import BLOCKED_EXTENSIONS, BLOCKED_SCHEMES

DISCOVERY_BLOCKED_FILE_EXTENSIONS: tuple[str, ...] = tuple(
    extension for extension in BLOCKED_EXTENSIONS if extension != ".xml"
)

DISCOVERY_BLOCKED_SCHEMES: tuple[str, ...] = tuple(
    f"{scheme}:" for scheme in BLOCKED_SCHEMES
)

DISCOVERY_UTILITY_PATH_PARTS: frozenset[str] = frozenset(
    {
        "login",
        "signin",
        "signup",
        "register",
        "account",
        "cart",
        "checkout",
        "search",
    }
)

DISCOVERY_UTILITY_HOSTS: frozenset[str] = frozenset(
    {
        "login",
        "auth",
        "accounts",
    }
)

BAD_QUERY_KEYS: frozenset[str] = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
    }
)


def has_bad_query(url: str) -> bool:
    """Return whether URL contains tracking query parameters."""
    parsed = urlparse(url)

    for key, _ in parse_qsl(parsed.query, keep_blank_values=False):
        if key.lower() in BAD_QUERY_KEYS:
            return True

    return False


__all__ = [
    "BAD_QUERY_KEYS",
    "DISCOVERY_BLOCKED_FILE_EXTENSIONS",
    "DISCOVERY_BLOCKED_SCHEMES",
    "DISCOVERY_UTILITY_HOSTS",
    "DISCOVERY_UTILITY_PATH_PARTS",
    "has_bad_query",
]
