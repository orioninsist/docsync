"""Shared runtime context models for crawler orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class CrawlerRuntimeContext:
    """Immutable-looking container for crawler runtime dependencies.

    The context intentionally stores externally created collaborators without
    constructing them. This keeps dependency ownership inside ``CrawlerEngine``
    while making future SRP extraction safer and more explicit.
    """

    output_dir: Path
    database: Any
    logger: Any
    config: Any
    state: dict[str, Any] = field(default_factory=dict)

    def remember(self, key: str, value: Any) -> None:
        """Store runtime-only metadata for downstream extraction steps."""
        self.state[key] = value

    def recall(self, key: str, default: Any = None) -> Any:
        """Return runtime-only metadata without coupling callers to dict access."""
        return self.state.get(key, default)
