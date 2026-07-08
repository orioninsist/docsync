"""Compatibility wrapper for the modular discovery fetcher.

The public crawler API imports ``AsyncFetcher`` and ``FetchResult`` from this
module. The implementation lives in ``crawler.discovery_parts.fetcher`` to keep
this top-level module small and Pylint-compliant.
"""

from __future__ import annotations

from crawler.discovery_parts.fetcher import AsyncFetcher, FetchResult

__all__ = ["AsyncFetcher", "FetchResult"]
