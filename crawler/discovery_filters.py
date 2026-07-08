"""Typed discovery filter constants and helpers."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlparse

DISCOVERY_BLOCKED_FILE_EXTENSIONS: tuple[str, ...] = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
    ".mp4",
    ".webm",
    ".mov",
    ".avi",
    ".mp3",
    ".wav",
    ".css",
    ".js",
    ".mjs",
    ".json",
    ".rss",
    ".atom",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
)

DISCOVERY_BLOCKED_SCHEMES: tuple[str, ...] = (
    "mailto:",
    "tel:",
    "javascript:",
    "data:",
    "blob:",
    "file:",
    "ftp:",
)

DISCOVERY_UTILITY_PATH_PARTS: frozenset[str] = frozenset(
    {
        "_",
        "url",
        "setprefdomain",
        "preferences",
        "setprefs",
        "sorry",
        "search",
        "advanced_search",
        "imghp",
        "maps",
        "mail",
        "calendar",
        "drive",
        "forms",
        "photos",
        "shopping",
        "finance",
        "travel",
        "flights",
        "accounts",
        "signin",
        "login",
        "servicelogin",
        "oauth",
        "auth",
    }
)

DISCOVERY_UTILITY_HOSTS: frozenset[str] = frozenset(
    {
        "mail.google.com",
        "accounts.google.com",
        "calendar.google.com",
        "drive.google.com",
        "forms.google.com",
        "photos.google.com",
        "shopping.google.com",
        "payments.google.com",
        "myaccount.google.com",
        "myactivity.google.com",
    }
)

BAD_QUERY_KEYS: frozenset[str] = frozenset(
    {
        "continue",
        "url",
        "q",
        "source",
        "ved",
        "usg",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "fbclid",
        "gclid",
    }
)


def has_bad_query(url: str) -> str | None:
    """Return a stable block reason when a URL has redirect/tracking query keys."""
    parsed = urlparse(url)
    if not parsed.query:
        return None

    keys = {
        key.lower() for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
    }
    matched = sorted(keys.intersection(BAD_QUERY_KEYS))
    if not matched:
        return None

    return f"bad_query:{matched[0]}"


__all__ = [
    "BAD_QUERY_KEYS",
    "DISCOVERY_BLOCKED_FILE_EXTENSIONS",
    "DISCOVERY_BLOCKED_SCHEMES",
    "DISCOVERY_UTILITY_HOSTS",
    "DISCOVERY_UTILITY_PATH_PARTS",
    "has_bad_query",
]
