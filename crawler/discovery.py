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
from crawler.discovery_url_rules import score_url


_COMPAT_EXPORTS: dict[str, tuple[str, str]] = {
    "_promote_discovery_root": (
        "crawler.discovery_url_rules",
        "_promote_discovery_root",
    ),
    "certificate_transparency_subdomain_candidates": (
        "crawler.discovery_engine",
        "certificate_transparency_subdomain_candidates",
    ),
    "extract_real_urls_from_html": (
        "crawler.discovery_engine",
        "extract_real_urls_from_html",
    ),
    "fetch_text": (
        "crawler.discovery_engine",
        "fetch_text",
    ),
    "robots_sitemaps": (
        "crawler.discovery_engine",
        "robots_sitemaps",
    ),
    "sitemap_candidates": (
        "crawler.discovery_engine",
        "sitemap_candidates",
    ),
    "strict_normalize_discovery_url": (
        "crawler.discovery_url_rules",
        "strict_normalize_discovery_url",
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
certificate_transparency_subdomain_candidates = _lazy_callable(
    "certificate_transparency_subdomain_candidates"
)
extract_real_urls_from_html = _lazy_callable("extract_real_urls_from_html")
fetch_text = _lazy_callable("fetch_text")
robots_sitemaps = _lazy_callable("robots_sitemaps")
sitemap_candidates = _lazy_callable("sitemap_candidates")
strict_normalize_discovery_url = _lazy_callable("strict_normalize_discovery_url")
write_discovery_coverage_report = _lazy_callable("write_discovery_coverage_report")


def score_discovered_url(url: str, seed_url: str) -> DiscoveryResult:
    """Compatibility wrapper for crawler.discovery_score.score_discovered_url."""
    from crawler.discovery_score import score_discovered_url as _score_discovered_url

    return _score_discovered_url(url, seed_url)


__all__ = [
    "DiscoveryResult",
    "_promote_discovery_root",
    "certificate_transparency_subdomain_candidates",
    "extract_real_urls_from_html",
    "fetch_text",
    "robots_sitemaps",
    "score_discovered_url",
    "score_url",
    "sitemap_candidates",
    "strict_normalize_discovery_url",
    "write_discovery_coverage_report",
]
