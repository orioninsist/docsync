"""Backward-compatible facade for legacy discovery imports.

This module preserves the remaining historical ``crawler.discovery`` import
surface while delegating implementation work to focused discovery modules.

New code should import from ``crawler.discovery_public`` or the focused owner
module directly.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlparse

import aiohttp

from crawler.discovery_report import write_discovery_coverage_report
from crawler.discovery_score import (
    DiscoveryResult,
    promote_discovery_root,
    score_discovered_url,
)
from crawler.discovery_url_rules import (
    HIGH_VALUE_PATH_HINTS,
    is_bad_url,
    is_blocked_machine_file,
    is_non_english_query,
    looks_like_official_host,
    normalize_candidate_url,
    path_parts,
    root_domain,
    same_scope,
    score_url,
)

DISCOVERY_CONNECT_TIMEOUT_SECONDS = 10
DISCOVERY_REQUEST_TIMEOUT_SECONDS = 20

_REDIRECT_TARGET_PARAMS = frozenset(
    {
        "url",
        "u",
        "uri",
        "target",
        "redirect",
        "redirect_url",
        "redirect_uri",
        "return",
        "return_to",
        "return_url",
        "next",
        "next_url",
        "continue",
        "continue_url",
        "dest",
        "destination",
        "to",
    }
)


def canonical_input(raw_url: str) -> str:
    """Return a stable canonical URL string for legacy discovery callers."""

    normalized = normalize_candidate_url(raw_url)
    return normalized or raw_url.strip()


def _redirect_param_targets(raw_url: str) -> list[str]:
    """Extract normalized URLs from common redirect query parameters."""

    parsed = urlparse(raw_url)
    targets = {
        normalized
        for key, value in parse_qsl(parsed.query, keep_blank_values=False)
        if key.lower() in _REDIRECT_TARGET_PARAMS
        if (normalized := normalize_candidate_url(value))
    }
    return sorted(targets)


async def _probe_final_working_root(
    session: aiohttp.ClientSession,
    *,
    seed_url: str,
    raw_url: str,
) -> str | None:
    """Return the promoted root of a reachable URL."""

    normalized = normalize_candidate_url(raw_url)

    if not normalized:
        return None

    try:
        async with session.get(
            normalized,
            allow_redirects=True,
        ) as response:
            if response.status >= 400:
                return None

            final_url = str(response.url)
    except Exception:
        return None

    return promote_discovery_root(seed_url, final_url)


async def _probe_redirect_final_roots(
    session: aiohttp.ClientSession,
    *,
    seed_url: str,
    raw_urls: list[str],
) -> list[str]:
    """Probe redirect candidates and return unique reachable roots."""

    roots: set[str] = set()

    for raw_url in raw_urls:
        candidate_urls = _redirect_param_targets(raw_url) or [raw_url]

        for candidate_url in candidate_urls:
            root = await _probe_final_working_root(
                session,
                seed_url=seed_url,
                raw_url=candidate_url,
            )

            if root is not None:
                roots.add(root)

    return sorted(roots)


def extract_real_urls_from_html(html: str, base_url: str) -> list[str]:
    """Delegate HTML link extraction to its focused owner module."""

    from crawler.discovery_links import extract_real_urls_from_html as extract_urls

    return extract_urls(
        html,
        base_url,
        normalize=normalize_candidate_url,
    )


def _fallback_discovery_candidates(seed_url: str) -> list[str]:
    """Return the canonical seed when network discovery cannot finish."""

    return [normalize_candidate_url(seed_url)]


async def discover(
    seed_url: str,
    *,
    limit: int,
    include_review: bool = False,
) -> tuple[list[DiscoveryResult], list[DiscoveryResult], list[DiscoveryResult]]:
    """Run legacy asynchronous discovery and classify scored candidates."""

    from crawler.discovery_engine import recursive_bfs_discovery_candidates

    timeout = aiohttp.ClientTimeout(
        total=DISCOVERY_REQUEST_TIMEOUT_SECONDS,
        connect=DISCOVERY_CONNECT_TIMEOUT_SECONDS,
        sock_connect=DISCOVERY_CONNECT_TIMEOUT_SECONDS,
        sock_read=DISCOVERY_REQUEST_TIMEOUT_SECONDS,
    )

    candidates: list[str]
    blocked: list[DiscoveryResult]

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

    scored = [score_discovered_url(seed_url, candidate) for candidate in candidates]
    scored.sort(key=lambda item: (-item.score, item.url))

    accepted = [item for item in scored if item.score >= 2]
    review = [item for item in scored if item.score < 2 and include_review]

    return accepted[:limit], blocked, review[:limit]


_promote_discovery_root = promote_discovery_root


__all__ = [
    "DISCOVERY_CONNECT_TIMEOUT_SECONDS",
    "DISCOVERY_REQUEST_TIMEOUT_SECONDS",
    "DiscoveryResult",
    "HIGH_VALUE_PATH_HINTS",
    "_probe_final_working_root",
    "_probe_redirect_final_roots",
    "_promote_discovery_root",
    "_redirect_param_targets",
    "canonical_input",
    "discover",
    "extract_real_urls_from_html",
    "is_bad_url",
    "is_blocked_machine_file",
    "is_non_english_query",
    "looks_like_official_host",
    "normalize_candidate_url",
    "path_parts",
    "root_domain",
    "same_scope",
    "score_discovered_url",
    "score_url",
    "write_discovery_coverage_report",
]
