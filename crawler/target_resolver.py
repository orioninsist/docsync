"""Target resolution helpers for crawler CLI commands.

This module owns only target classification and target normalization.
It intentionally has no dependency on CLI parsing, runtime paths, database
state, logging, or crawling orchestration.
"""

from __future__ import annotations

from pathlib import Path


def target_is_file(target: str) -> bool:
    """Return True when the target points to a likely file path.

    The check is intentionally conservative and filesystem-independent:
    it does not require the path to exist.
    """

    target_path = Path(target)
    return bool(target_path.suffix)


def resolve_target(target: str, workspace: str | None) -> tuple[list[str], str | None]:
    """Resolve target and workspace while preserving CLI compatibility."""

    normalized = target.strip()
    if not normalized:
        raise ValueError("Target cannot be empty.")

    if workspace:
        return [normalized], workspace.strip() or None

    if target_is_file(normalized):
        target_path = Path(normalized)
        return [normalized], target_path.parent.name or None

    return [normalized], None
