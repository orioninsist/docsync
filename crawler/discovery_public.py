"""Public asynchronous discovery orchestration."""

from __future__ import annotations

import aiohttp

from crawler.discovery_engine import recursive_bfs_discovery_candidates
from crawler.discovery_result import DiscoveryResult
from crawler.discovery_score import score_discovered_url
from crawler.discovery_url_rules import normalize_candidate_url

DISCOVERY_CONNECT_TIMEOUT_SECONDS = 10
DISCOVERY_REQUEST_TIMEOUT_SECONDS = 20


def _fallback_discovery_candidates(seed_url: str) -> list[str]:
    """Return the canonical seed when network discovery cannot finish."""

    return [normalize_candidate_url(seed_url)]


async def discover(
    seed_url: str,
    *,
    limit: int,
) -> tuple[list[DiscoveryResult], list[DiscoveryResult], list[DiscoveryResult]]:
    """Discover and classify candidate URLs for a seed URL."""

    timeout = aiohttp.ClientTimeout(
        total=DISCOVERY_REQUEST_TIMEOUT_SECONDS,
        connect=DISCOVERY_CONNECT_TIMEOUT_SECONDS,
        sock_connect=DISCOVERY_CONNECT_TIMEOUT_SECONDS,
        sock_read=DISCOVERY_REQUEST_TIMEOUT_SECONDS,
    )

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            candidates, blocked = await recursive_bfs_discovery_candidates(
                session,
                base_url=seed_url,
                limit=limit,
            )
    except aiohttp.ClientError as exc:
        print(
            f"[WARNING] Discovery network failure: {seed_url}: {exc}",
            flush=True,
        )
        print(
            "[CONTINUE] Falling back to the canonical seed URL.",
            flush=True,
        )
        candidates = _fallback_discovery_candidates(seed_url)
        blocked = []

    accepted = [
        score_discovered_url(seed_url, candidate) for candidate in candidates[:limit]
    ]

    return accepted, blocked, []


__all__ = [
    "DISCOVERY_CONNECT_TIMEOUT_SECONDS",
    "DISCOVERY_REQUEST_TIMEOUT_SECONDS",
    "discover",
]
