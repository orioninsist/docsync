"""Shared immutable value types used by recursive discovery."""

from __future__ import annotations

from typing import NamedTuple


class DiscoveryQueueItem(NamedTuple):
    """Queued URL plus traversal metadata."""

    url: str
    depth: int
    discovered_from: str | None


class DiscoveryScore(NamedTuple):
    """Simple quality score for a discovered URL."""

    score: int
