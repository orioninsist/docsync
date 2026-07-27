"""Discovery result construction and root-promotion services."""

from __future__ import annotations

from urllib.parse import urlparse

from crawler.discovery_result import DiscoveryResult
from crawler.discovery_scope import build_discovery_policy
from crawler.discovery_url_rules import (
    HIGH_VALUE_PATH_HINTS,
    REGION_GATEKEEPER_SAFE_HOST_PREFIXES,
    normalize_candidate_url,
    path_parts,
)


def score_discovered_url(seed_url: str, url: str) -> DiscoveryResult:
    """Return one normalized discovery result without calculating a score."""

    del seed_url

    return DiscoveryResult(
        url=normalize_candidate_url(url),
        source="discovery",
        score=0,
        reason="discovered",
    )


def promote_discovery_root(seed_url: str, url: str) -> str:
    """Promote a valuable in-scope candidate to its host root."""

    clean_url = normalize_candidate_url(url)
    parsed_url = urlparse(clean_url)
    host = parsed_url.netloc.lower()

    if not host:
        return clean_url.rstrip("/") + "/"

    normalized_host = build_discovery_policy(seed_url).normalize_host(host)
    host_prefix = normalized_host.split(".", maxsplit=1)[0]
    candidate_path_parts = frozenset(path_parts(clean_url))

    has_promotable_host_prefix = host_prefix in REGION_GATEKEEPER_SAFE_HOST_PREFIXES
    has_high_value_path = bool(candidate_path_parts.intersection(HIGH_VALUE_PATH_HINTS))
    belongs_to_seed_scope = build_discovery_policy(seed_url).same_scope(clean_url)

    if belongs_to_seed_scope and (has_promotable_host_prefix or has_high_value_path):
        scheme = parsed_url.scheme or "https"
        return f"{scheme}://{host}/"

    return clean_url.rstrip("/") + "/"


__all__ = [
    "promote_discovery_root",
    "score_discovered_url",
]
