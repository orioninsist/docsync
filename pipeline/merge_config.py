"""Central configuration contract for Markdown merge planning."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


DEFAULT_MAX_SOURCES_PER_TARGET: Final[int] = 40


class MergeStrategy(StrEnum):
    """Supported document grouping strategies."""

    FIXED_SIZE = "fixed_size"


class MergeConfigurationError(ValueError):
    """Raised when merge configuration violates its contract."""


@dataclass(frozen=True, slots=True)
class MergeConfig:
    """Contain immutable user-controlled merge behavior."""

    strategy: MergeStrategy = MergeStrategy.FIXED_SIZE
    max_sources_per_target: int = DEFAULT_MAX_SOURCES_PER_TARGET

    def __post_init__(self) -> None:
        """Validate configuration at the application boundary."""
        if self.max_sources_per_target < 1:
            raise MergeConfigurationError(
                "Maximum sources per target must be greater than zero."
            )


DEFAULT_MERGE_CONFIG: Final[MergeConfig] = MergeConfig()


__all__ = [
    "DEFAULT_MAX_SOURCES_PER_TARGET",
    "DEFAULT_MERGE_CONFIG",
    "MergeConfig",
    "MergeConfigurationError",
    "MergeStrategy",
]
