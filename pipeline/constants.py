"""Shared constants used across the document processing pipeline."""

from __future__ import annotations

from typing import Final

READ_ONLY_MODE: Final[int] = 0o444
WRITE_MODE: Final[int] = 0o644

STATE_DIRECTORY_NAME: Final[str] = ".state"

FLATTEN_DATABASE_NAME: Final[str] = "flatten.db"
INCREMENTAL_DATABASE_NAME: Final[str] = "incremental.db"

MERGED_DIRECTORY_NAME: Final[str] = "_merged"
MERGED_STATE_DIRECTORY_NAME: Final[str] = "state"

LEGACY_MERGE_DATABASE_NAME: Final[str] = ".merge_state.db"

IGNORED_DIRECTORY_NAMES: Final[frozenset[str]] = frozenset(
    {
        "_merged",
        "_archive",
        "_raw",
        STATE_DIRECTORY_NAME,
    }
)

__all__ = [
    "READ_ONLY_MODE",
    "WRITE_MODE",
    "STATE_DIRECTORY_NAME",
    "FLATTEN_DATABASE_NAME",
    "INCREMENTAL_DATABASE_NAME",
    "MERGED_DIRECTORY_NAME",
    "MERGED_STATE_DIRECTORY_NAME",
    "LEGACY_MERGE_DATABASE_NAME",
    "IGNORED_DIRECTORY_NAMES",
]
