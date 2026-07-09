"""Backward-compatible discovery facade.

This module intentionally owns no discovery implementation logic. It keeps
legacy imports stable while resolving symbols from focused modules lazily.

New code should prefer importing directly from the focused modules, especially
crawler.discovery_public.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from crawler.discovery_types import DiscoveryResult
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


_COMPAT_EXPORTS: dict[str, tuple[str, str]] = {
    "_promote_discovery_root": (
        "crawler.discovery_url_rules",
        "_promote_discovery_root",
    ),
    "write_discovery_coverage_report": (
        "crawler.discovery_writer",
        "write_discovery_coverage_report",
    ),
}


def _resolve_export(name: str) -> Any:
    """Resolve a legacy export without importing implementation modules eagerly."""
    import importlib

    module_name, symbol_name = _COMPAT_EXPORTS[name]
    module = importlib.import_module(module_name)
    value = getattr(module, symbol_name)
    globals()[name] = value
    return value


def __getattr__(name: str) -> Any:
    """Resolve legacy discovery symbols on demand."""
    if name in _COMPAT_EXPORTS:
        return _resolve_export(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _lazy_callable(name: str) -> Callable[..., Any]:
    """Create a small callable proxy for legacy ``from crawler.discovery import`` use."""

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        target = _resolve_export(name)
        return target(*args, **kwargs)

    wrapper.__name__ = name
    wrapper.__qualname__ = name
    wrapper.__module__ = __name__
    return wrapper


_promote_discovery_root = _lazy_callable("_promote_discovery_root")
write_discovery_coverage_report = _lazy_callable("write_discovery_coverage_report")


async def fetch_text(session: Any, url: str) -> str | None:
    """Fetch text content for legacy discovery callers."""
    try:
        async with session.get(url, allow_redirects=True) as response:
            if response.status >= 400:
                return None
            return await response.text()
    except Exception:
        return None


async def robots_sitemaps(session: Any, base_url: str) -> list[str]:
    """Compatibility placeholder for removed robots/sitemap seed expansion."""
    del session, base_url
    return []


async def sitemap_candidates(session: Any, base_url: str) -> list[str]:
    """Compatibility placeholder for removed sitemap candidate expansion."""
    del session, base_url
    return []


async def certificate_transparency_subdomain_candidates(
    session: Any,
    base_url: str,
    *,
    max_hosts: int = 0,
) -> list[str]:
    """Compatibility placeholder for removed CT subdomain expansion."""
    del session, base_url, max_hosts
    return []


def extract_real_urls_from_html(html: str, base_url: str) -> list[str]:
    """Compatibility wrapper for HTML URL extraction."""
    from crawler.discovery_links import extract_real_urls_from_html as _extract

    return _extract(html, base_url, normalize=normalize_candidate_url)


def strict_normalize_discovery_url(
    raw_url: str,
    *,
    base_url: str | None = None,
) -> str | None:
    """Compatibility alias for the removed strict discovery normalizer."""
    del base_url
    return normalize_candidate_url(raw_url)


def score_discovered_url(url: str, seed_url: str) -> DiscoveryResult:
    """Compatibility wrapper for crawler.discovery_score.score_discovered_url."""
    from crawler.discovery_score import score_discovered_url as _score_discovered_url

    return _score_discovered_url(url, seed_url)


async def discover(
    seed_url: str,
    *,
    limit: int,
    include_review: bool = False,
) -> tuple[list[DiscoveryResult], list[DiscoveryResult], list[DiscoveryResult]]:
    """Compatibility wrapper for the legacy async discovery API.

    Returns:
        A tuple of ``accepted, blocked, review`` discovery results.
    """
    import aiohttp

    from crawler.discovery_engine import recursive_bfs_discovery_candidates

    async with aiohttp.ClientSession() as session:
        candidates, blocked = await recursive_bfs_discovery_candidates(
            session,
            base_url=seed_url,
            limit=limit,
        )

    scored = [score_discovered_url(candidate, seed_url) for candidate in candidates]
    scored.sort(key=lambda item: (-item.score, item.url))

    accepted: list[DiscoveryResult] = []
    review: list[DiscoveryResult] = []

    for item in scored:
        if item.score >= 2:
            accepted.append(item)
        elif include_review:
            review.append(item)

    return accepted[:limit], blocked, review[:limit]


__all__ = [
    "DiscoveryResult",
    "discover",
    "HIGH_VALUE_PATH_HINTS",
    "_promote_discovery_root",
    "certificate_transparency_subdomain_candidates",
    "extract_real_urls_from_html",
    "fetch_text",
    "is_bad_url",
    "is_blocked_machine_file",
    "is_non_english_query",
    "looks_like_official_host",
    "normalize_candidate_url",
    "path_parts",
    "robots_sitemaps",
    "root_domain",
    "same_scope",
    "score_discovered_url",
    "score_url",
    "sitemap_candidates",
    "strict_normalize_discovery_url",
    "write_discovery_coverage_report",
]
