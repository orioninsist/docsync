"""Compatibility exports for discovery reporting.

This module keeps the historical import path stable while delegating the actual
coverage report writer to the dedicated writer module. It intentionally contains
no reporting implementation.
"""

from __future__ import annotations

from crawler.discovery_types import DiscoveryResult
from crawler.discovery_writer import write_discovery_coverage_report

__all__ = ["DiscoveryResult", "write_discovery_coverage_report"]
