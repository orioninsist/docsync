"""Public scoring facade for discovered documentation URLs.

This module isolates discovery scoring consumers from legacy implementation
details exposed by crawler.discovery and crawler.discovery_url_rules.
"""

from __future__ import annotations

from crawler.discovery import _promote_discovery_root, score_url
from crawler.discovery_result import DiscoveryResult
from crawler.discovery_url_rules import official_host_confidence


def score_discovered_url(url: str, seed_url: str) -> DiscoveryResult:
    """Score one discovered URL and return the public discovery result."""
    scored_results = score_url(url, seed=seed_url)

    if not scored_results:
        return DiscoveryResult(
            url=url,
            source="score_url",
            score=0,
            reason="no_scoring_result",
        )

    scored = scored_results[0]

    return DiscoveryResult(
        url=scored.url,
        source="score_url",
        score=scored.score,
        reason=scored.reason,
    )


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
