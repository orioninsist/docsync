from __future__ import annotations

DISCOVERY_BLOCKED_HOST_EXACT = {
    "g",
    "localhost",
}

DISCOVERY_BLOCKED_HOST_SUFFIXES = (
    ".local",
    ".localhost",
    ".internal",
    ".invalid",
    ".test",
    ".example",
)

DISCOVERY_BLOCKED_FILE_EXTENSIONS = (
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

DISCOVERY_BLOCKED_SCHEMES = (
    "mailto:",
    "tel:",
    "javascript:",
    "data:",
    "blob:",
    "file:",
    "ftp:",
)

DISCOVERY_MAX_DEFAULT_PAGES = 900
DISCOVERY_MAX_DEFAULT_DEPTH = 5
DISCOVERY_MAX_LINKS_PER_PAGE = 2500
DISCOVERY_MAX_ACCEPTED_MULTIPLIER = 30

DISCOVERY_QUALITY_EXTRA_SCAN_PAGES = 250
DISCOVERY_MIN_GOOD_SCORE = 95
DISCOVERY_MAX_NO_NEW_GOOD = 120
