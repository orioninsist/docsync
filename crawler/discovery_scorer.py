"""Discovery scoring helpers.

This module keeps scorer-related compatibility wrappers isolated from the
legacy discovery module so strict MyPy does not depend on implicit exports.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from crawler.discovery_score import promote_discovery_root

__all__ = [
    "collapse_to_crawl_root",
    "official_host_confidence",
    "path_depth",
    "path_part_set",
    "prune_child_roots",
    "score_promote_discovery_root",
]


def official_host_confidence(url: str) -> int:
    """Return a simple confidence score for an official-looking host."""
    host = urlsplit(url).netloc.lower()
    if not host:
        return 0
    if host.startswith("www."):
        return 100
    if host.count(".") <= 1:
        return 90
    return 70


def path_part_set(url: str) -> set[str]:
    """Return normalized non-empty path parts for a URL."""
    return {part for part in urlsplit(url).path.lower().split("/") if part}


def path_depth(url: str) -> int:
    """Return the number of normalized non-empty URL path parts."""
    return len(path_part_set(url))


def collapse_to_crawl_root(url: str) -> str:
    """Collapse a URL to its scheme and host crawl root."""
    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def prune_child_roots(urls: list[str]) -> list[str]:
    """Remove crawl roots that are children of another selected root."""
    roots = sorted({collapse_to_crawl_root(url) for url in urls})
    pruned: list[str] = []

    for root in roots:
        if not any(
            root != parent and root.startswith(f"{parent}/") for parent in pruned
        ):
            pruned.append(root)

    return pruned


def score_promote_discovery_root(seed: str, url: str) -> str:
    """Return the promoted discovery root for a seed and candidate URL."""
    return promote_discovery_root(seed, url)
