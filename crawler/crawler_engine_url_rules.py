"""Pure URL rule helpers for crawler engine decisions.

This module intentionally contains no network, filesystem, database, logging,
or crawler-state access. It exists so integration-heavy crawler code can
delegate deterministic URL decisions to small, independently testable helpers.
"""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import urlsplit


DEFAULT_HARD_BLACKLIST_SUBSTRINGS: tuple[str, ...] = (
    "/cdn-cgi/",
    "/wp-admin/",
    "/wp-login.php",
    "/xmlrpc.php",
    "/admin/",
    "/login",
    "/logout",
    "/signin",
    "/sign-in",
    "/signup",
    "/sign-up",
    "/register",
    "/cart",
    "/checkout",
    "/basket",
    "/my-account",
    "/account",
    "/user/",
    "/users/",
    "/profile",
    "/privacy",
    "/terms",
    "/cookie",
    "/cookies",
    "/legal",
    "/license",
    "/licenses",
    "/search",
    "?s=",
    "?q=",
    "&q=",
    "/tag/",
    "/tags/",
    "/category/",
    "/categories/",
    "/author/",
    "/feed",
    "/rss",
    "/atom",
    ".xml",
    ".json",
    ".rss",
    ".atom",
)


DEFAULT_HARD_BLACKLIST_EXTENSIONS: tuple[str, ...] = (
    ".7z",
    ".apk",
    ".avi",
    ".bin",
    ".bmp",
    ".bz2",
    ".css",
    ".csv",
    ".dmg",
    ".doc",
    ".docx",
    ".eot",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".iso",
    ".jpeg",
    ".jpg",
    ".js",
    ".m4a",
    ".m4v",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".odp",
    ".ods",
    ".odt",
    ".ogg",
    ".ogv",
    ".otf",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".rar",
    ".rtf",
    ".svg",
    ".tar",
    ".tgz",
    ".tif",
    ".tiff",
    ".ttf",
    ".wav",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
    ".xls",
    ".xlsx",
    ".zip",
)


def is_hard_blacklisted_url(
    url: str,
    *,
    blocked_substrings: Iterable[str] = DEFAULT_HARD_BLACKLIST_SUBSTRINGS,
    blocked_extensions: Iterable[str] = DEFAULT_HARD_BLACKLIST_EXTENSIONS,
) -> bool:
    """Return whether a URL should be rejected before expensive crawling work.

    The function is deliberately conservative and deterministic. It rejects
    malformed URLs, non-HTTP(S) schemes, obvious binary/static assets, and
    high-noise paths that are not useful for documentation/content crawling.
    """

    normalized_url = url.strip().lower()
    if not normalized_url:
        return True

    parsed_url = urlsplit(normalized_url)
    if parsed_url.scheme not in {"http", "https"}:
        return True

    if not parsed_url.netloc:
        return True

    path = parsed_url.path.rstrip("/")
    query = f"?{parsed_url.query}" if parsed_url.query else ""
    path_and_query = f"{path}{query}"

    if any(substring in path_and_query for substring in blocked_substrings):
        return True

    return path.endswith(tuple(blocked_extensions))


__all__ = [
    "DEFAULT_HARD_BLACKLIST_EXTENSIONS",
    "DEFAULT_HARD_BLACKLIST_SUBSTRINGS",
    "is_hard_blacklisted_url",
]
