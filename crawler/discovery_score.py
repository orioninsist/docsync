"""Public scoring and root-promotion services for discovery candidates."""

from __future__ import annotations

from urllib.parse import urlparse

from crawler.discovery_result import DiscoveryResult
from crawler.discovery_url_rules import (
    HIGH_VALUE_PATH_HINTS,
    REGION_GATEKEEPER_SAFE_HOST_PREFIXES,
    normalize_candidate_url,
    path_parts,
    score_url,
)


def score_discovered_url(seed_url: str, url: str) -> DiscoveryResult:
    """Score one discovered URL and return its public result."""

    results = score_url(url, seed=seed_url)
    if not results:
        raise ValueError("score_url returned no result for the supplied URL")

    result = results[0]
    return DiscoveryResult(
        url=result.url,
        score=result.score,
        reason=result.reason,
        source="score_url",
    )


def official_host_confidence(url: str, seed_host: str) -> bool:
    """Return whether a candidate belongs to the seed host namespace."""

    candidate_host = urlparse(normalize_candidate_url(url)).hostname
    normalized_seed_host = _normalize_host(seed_host)

    if not candidate_host or not normalized_seed_host:
        return False

    normalized_candidate_host = _normalize_host(candidate_host)
    return (
        normalized_candidate_host == normalized_seed_host
        or normalized_candidate_host.endswith(f".{normalized_seed_host}")
        or normalized_seed_host.endswith(f".{normalized_candidate_host}")
    )


def promote_discovery_root(seed_url: str, url: str) -> str:
    """Promote a valuable same-host candidate to its discovery root."""

    clean_url = normalize_candidate_url(url)
    parsed_url = urlparse(clean_url)
    host = parsed_url.netloc.lower()

    if not host:
        return clean_url.rstrip("/") + "/"

    normalized_host = _normalize_host(host)
    host_prefix = normalized_host.split(".", maxsplit=1)[0]
    candidate_path_parts = frozenset(path_parts(clean_url))

    has_promotable_host_prefix = host_prefix in REGION_GATEKEEPER_SAFE_HOST_PREFIXES
    has_high_value_path = bool(candidate_path_parts.intersection(HIGH_VALUE_PATH_HINTS))

    seed_host = urlparse(normalize_candidate_url(seed_url)).netloc
    belongs_to_seed_host = bool(
        seed_url and official_host_confidence(clean_url, seed_host)
    )

    if belongs_to_seed_host and (has_promotable_host_prefix or has_high_value_path):
        scheme = parsed_url.scheme or "https"
        return f"{scheme}://{host}/"

    return clean_url.rstrip("/") + "/"


def _normalize_host(host: str) -> str:
    """Normalize a hostname for deterministic scope comparisons."""

    normalized = host.strip().lower().split(":", maxsplit=1)[0]
    return normalized.removeprefix("www.")


__all__ = [
    "DiscoveryResult",
    "official_host_confidence",
    "promote_discovery_root",
    "score_discovered_url",
    "score_url",
]
