"""Discovery root gate helpers with safe import boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from urllib.parse import urlparse

from crawler import config
from crawler.discovery_score import (
    promote_discovery_root as score_promote_discovery_root,
)

_NON_ENGLISH_LANGUAGE_SEGMENTS: Final[frozenset[str]] = frozenset(
    getattr(
        config,
        "NON_ENGLISH_LANGUAGE_SEGMENTS",
        {
            "ar",
            "de",
            "es",
            "fr",
            "it",
            "ja",
            "ko",
            "nl",
            "pl",
            "pt",
            "ru",
            "tr",
            "uk",
            "zh",
        },
    )
)

_MEDIA_SUFFIXES: Final[tuple[str, ...]] = (
    ".avi",
    ".css",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".m4v",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".pdf",
    ".png",
    ".svg",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
    ".xml",
    ".zip",
)


@dataclass(frozen=True, slots=True)
class RootGateDecision:
    """Decision returned by the discovery root gate."""

    allowed: bool
    url: str
    reason: str = ""


def raw_discovery_block_reason(url: str) -> str:
    """Return a deterministic block reason for unsuitable discovery roots."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    host_parts = tuple(part for part in parsed.netloc.lower().split(".") if part)
    path_parts = tuple(part for part in path.split("/") if part)

    if parsed.scheme not in {"http", "https"}:
        return "unsupported-scheme"

    if not parsed.netloc:
        return "missing-host"

    if any(part in _NON_ENGLISH_LANGUAGE_SEGMENTS for part in host_parts):
        return "non-english-host-segment"

    if any(part in _NON_ENGLISH_LANGUAGE_SEGMENTS for part in path_parts):
        return "non-english-path-segment"

    if path.endswith(_MEDIA_SUFFIXES):
        return "media-or-non-html-resource"

    return ""


def promote_discovery_root(url: str, *, seed: str) -> str:
    """Promote a discovered URL to a stable root candidate."""
    return score_promote_discovery_root(seed, url)


def final_txt_candidate(url: str) -> str:
    """Normalize a URL before writing it into the editable queue TXT."""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url.strip()

    normalized_path = parsed.path or "/"
    return parsed._replace(
        fragment="",
        path=normalized_path,
    ).geturl()


def evaluate_discovery_root(url: str, *, seed: str) -> RootGateDecision:
    """Evaluate and normalize a discovery root candidate."""
    block_reason = raw_discovery_block_reason(url)
    if block_reason:
        return RootGateDecision(False, url, block_reason)

    promoted = promote_discovery_root(url, seed=seed)
    candidate = final_txt_candidate(promoted)
    return RootGateDecision(True, candidate)


__all__ = [
    "RootGateDecision",
    "evaluate_discovery_root",
    "final_txt_candidate",
    "promote_discovery_root",
    "raw_discovery_block_reason",
]
