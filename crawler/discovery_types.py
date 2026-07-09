"""Backward-compatible discovery type exports.

This module is intentionally kept as a thin compatibility shim while older
call sites are migrated to crawler.discovery_result. The canonical
DiscoveryResult implementation lives in crawler.discovery_result.
"""

from __future__ import annotations

from crawler.discovery_result import DiscoveryResult

__all__ = ["DiscoveryResult"]
