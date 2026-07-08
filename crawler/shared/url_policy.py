from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlparse

from crawler.shared.url_normalizer import (
    normalize_url,
    url_declares_non_english,
    url_is_explicitly_english_or_neutral,
)


@dataclass(frozen=True)
class UrlPolicyResult:
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

BLOCKED_EXTENSIONS = (
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
    ".xml",
    ".rss",
    ".atom",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
)

ALLOWED_TEXT_CONTENT_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "text/plain",
)

BLOCKED_CONTENT_TYPE_MARKERS = (
    "application/pdf",
    "application/zip",
    "application/x-zip-compressed",
    "application/x-rar",
    "application/x-7z-compressed",
    "application/x-tar",
    "application/gzip",
    "application/octet-stream",
    "image/",
    "video/",
    "audio/",
    "font/",
)

TRAP_PATH_PARTS = {
    "login",
    "logout",
    "signin",
    "sign-in",
    "sign_in",
    "auth",
    "auth0",
    "oauth",
    "account",
    "accounts",
    "profile",
    "profiles",
    "user",
    "users",
    "client",
    "clients",
    "cart",
    "checkout",
    "basket",
    "search",
    "requests",
    "request",
    "comment",
    "comments",
    "reply",
    "replies",
    "forum",
    "forums",
    "community",
    "thread",
    "threads",
    "discussion",
    "discussions",
    "video",
    "videos",
    "reel",
    "reels",
    "shorts",
}

TRAP_QUERY_KEYS = {
    "q",
    "query",
    "search",
    "search_id",
    "results_count",
    "rank",
    "return_to",
    "redirect",
    "redirect_to",
    "callback",
    "data",
    "url",
    "continue",
    "next",
}

MEDIA_SOCIAL_HOSTS = {
    "instagram.com",
    "tiktok.com",
    "youtube.com",
    "youtu.be",
    "facebook.com",
    "x.com",
    "twitter.com",
    "threads.net",
    "snapchat.com",
    "pinterest.com",
    "reddit.com",
    "vimeo.com",
    "dailymotion.com",
    "twitch.tv",
}


def normalize_policy_url(url: str) -> str | None:
    try:
        return normalize_url(url)
    except Exception:
        return None


def is_allowed_text_content_type(content_type: str) -> bool:
    lowered = (content_type or "").lower()
    return any(item in lowered for item in ALLOWED_TEXT_CONTENT_TYPES)


def is_blocked_content_type(content_type: str) -> bool:
    lowered = (content_type or "").lower()
    return any(item in lowered for item in BLOCKED_CONTENT_TYPE_MARKERS)


def host_is_media_or_social(host: str) -> bool:
    host = host.lower().removeprefix("www.")
    return any(host == item or host.endswith("." + item) for item in MEDIA_SOCIAL_HOSTS)


def path_has_blocked_extension(path: str) -> bool:
    return path.lower().endswith(BLOCKED_EXTENSIONS)


def path_parts(path: str) -> set[str]:
    return {
        part.strip().lower().replace("_", "-")
        for part in path.strip("/").split("/")
        if part.strip()
    }


def has_trap_query(query: str) -> bool:
    for key, _ in parse_qsl(query, keep_blank_values=False):
        if key.lower().strip() in TRAP_QUERY_KEYS:
            return True
    return False


def evaluate_url_before_network(
    url: str, *, require_english: bool = True
) -> UrlPolicyResult:
    normalized = normalize_policy_url(url)

    if normalized is None:
        return UrlPolicyResult(False, "invalid_url", None)

    parsed = urlparse(normalized)
    scheme = parsed.scheme.lower()
    host = parsed.netloc.lower().removeprefix("www.")

    if scheme not in {"http", "https"} or scheme in BLOCKED_SCHEMES:
        return UrlPolicyResult(False, "blocked_scheme", normalized)

    if not host:
        return UrlPolicyResult(False, "missing_host", normalized)

    if host_is_media_or_social(host):
        return UrlPolicyResult(False, "media_or_social_host", normalized)

    if path_has_blocked_extension(parsed.path):
        return UrlPolicyResult(False, "blocked_file_extension", normalized)

    if path_parts(parsed.path).intersection(TRAP_PATH_PARTS):
        return UrlPolicyResult(False, "trap_path", normalized)

    if has_trap_query(parsed.query):
        return UrlPolicyResult(False, "trap_query", normalized)

    if require_english and not url_is_explicitly_english_or_neutral(normalized):
        return UrlPolicyResult(False, "non_english_url", normalized)

    if require_english and url_declares_non_english(normalized):
        return UrlPolicyResult(False, "non_english_locale", normalized)

    return UrlPolicyResult(True, "allowed", normalized)
