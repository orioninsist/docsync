"""Typed compatibility gate for discovery URL canonicalization."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import cast

CanonicalInput = Callable[[str], str]


def _load_canonical_input() -> CanonicalInput:
    """Load crawler.discovery.canonical_input without mypy attr-defined noise."""
    discovery_module = import_module("crawler.discovery")
    return cast(CanonicalInput, getattr(discovery_module, "canonical_input"))


canonical_input = _load_canonical_input()

__all__ = ["canonical_input"]
