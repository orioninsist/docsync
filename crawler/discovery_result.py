"""Discovery result data model.

This module intentionally contains only the immutable result contract used by
site discovery workflows. Keeping the model isolated prevents discovery logic,
scoring logic, redirect handling, and queue persistence from depending on the
large crawler.discovery module.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """Final normalized result produced by discovery workflows."""

    url: str
    source: str
    score: int
    reason: str
