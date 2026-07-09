"""Stable public discovery API.

This module exposes the small, dependency-light discovery contracts that other
parts of the application may safely import without pulling in the legacy
discovery implementation.

New code should prefer this facade over importing from crawler.discovery.
"""

from __future__ import annotations

from crawler.discovery_report import write_discovery_coverage_report
from crawler.discovery_result import DiscoveryResult
from crawler.discovery_score import score_discovered_url
from crawler.discovery_url_rules import score_url

__all__ = [
    "DiscoveryResult",
    "score_discovered_url",
    "score_url",
    "write_discovery_coverage_report",
]
