"""Shared URL policy constants and helpers."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class UrlPolicyResult:
    """Result of URL policy validation."""

    allowed: bool
    reason: str
    normalized_url: str | None = None


BLOCKED_SCHEMES = {
    "mailto",
    "tel",
    "javascript",
    "data",
    "blob",
    "file",
    "ftp",
}

BLOCKED_LINK_PREFIXES = (
    "#",
    *(f"{scheme}:" for scheme in BLOCKED_SCHEMES),
)

BLOCKED_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
)

TRAP_PATH_PARTS = {
    "login",
    "signin",
    "signup",
    "register",
    "account",
    "profile",
    "profiles",
    "subscribe",
    "subscription",
    "subscriptions",
    "cart",
    "checkout",
}

TRAP_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "ref",
    "source",
    "affiliate",
}

MEDIA_SOCIAL_HOSTS = frozenset(
    {
        "facebook.com",
        "instagram.com",
        "twitter.com",
        "x.com",
        "linkedin.com",
        "youtube.com",
        "tiktok.com",
        "pinterest.com",
    }
)


def is_blocked_url(url: str) -> bool:
    """Return whether a URL is blocked by scheme policy."""
    normalized = url.strip().lower()

    if not normalized:
        return True

    parsed = urlparse(normalized)

    if parsed.scheme in BLOCKED_SCHEMES:
        return True

    if any(normalized.startswith(prefix) for prefix in BLOCKED_LINK_PREFIXES):
        return True

    return any(parsed.path.endswith(extension) for extension in BLOCKED_EXTENSIONS)


def host_is_media_or_social(host: str) -> bool:
    """Return True when host belongs to known media or social platforms."""
    normalized = host.lower().strip().removeprefix("www.")

    return normalized in MEDIA_SOCIAL_HOSTS or any(
        normalized.endswith(f".{blocked_host}")
        for blocked_host in MEDIA_SOCIAL_HOSTS
    )


def path_has_blocked_extension(path: str) -> bool:
    """Return True when path contains blocked file extension."""
    normalized = path.lower().strip()

    return any(normalized.endswith(extension) for extension in BLOCKED_EXTENSIONS)


def is_allowed_text_content_type(content_type: str) -> bool:
    """Return True for HTML or text based content types."""
    normalized = content_type.lower().strip()

    return normalized.startswith(
        (
            "text/",
            "application/xhtml+xml",
            "application/xml",
        )
    )


def is_blocked_content_type(content_type: str) -> bool:
    """Return True when content type is binary, media, or archive."""
    normalized = content_type.lower().strip()

    if not normalized:
        return False

    if is_allowed_text_content_type(normalized):
        return False

    blocked_prefixes = (
        "image/",
        "audio/",
        "video/",
        "application/pdf",
        "application/zip",
        "application/gzip",
        "application/octet-stream",
    )

    return normalized.startswith(blocked_prefixes)
