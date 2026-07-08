from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DiscoveryResult:
    url: str
    score: int
    reason: str
