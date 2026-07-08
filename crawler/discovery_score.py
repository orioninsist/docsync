"""Discovery scoring facade.

This module keeps scoring imports stable while the implementation lives in
crawler.discovery and crawler.discovery_url_rules.
"""

from __future__ import annotations

from crawler.discovery import DiscoveryResult, _promote_discovery_root, score_url
from crawler.discovery_url_rules import official_host_confidence


def score_discovered_url(seed_url: str, url: str) -> DiscoveryResult:
    """Score a discovered URL and return the public discovery result."""

    _bucket, result = score_url(url, seed=seed_url)
    return result


def promote_discovery_root(seed_url: str, url: str) -> str:
    """Promote a discovered URL to its canonical discovery root."""

    return _promote_discovery_root(seed_url, url)


__all__ = [
    "DiscoveryResult",
    "official_host_confidence",
    "promote_discovery_root",
    "score_discovered_url",
    "score_url",
]
