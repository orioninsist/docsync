"""Resolve DOCSYNC project paths without static project assumptions."""

from __future__ import annotations

from pathlib import Path
from typing import Final

SOURCES_DIR_NAME: Final = "sources"

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
SOURCES_ROOT: Final = PROJECT_ROOT / SOURCES_DIR_NAME


def resolve_sources_root(project_root: Path = PROJECT_ROOT) -> Path:
    """Return the absolute sources directory for a project root."""
    return project_root.resolve() / SOURCES_DIR_NAME


def normalize_project_name(project_name: str) -> str:
    """Validate and normalize one project directory name."""
    normalized_project_name = project_name.strip()

    if not normalized_project_name:
        raise ValueError("Project name must not be empty.")

    if normalized_project_name in {".", ".."}:
        raise ValueError("Project name must not be '.' or '..'.")

    if Path(normalized_project_name).name != normalized_project_name:
        raise ValueError(
            "Project name must be a single directory name without path separators."
        )

    return normalized_project_name


def resolve_project_directory(
    project_name: str,
    sources_root: Path = SOURCES_ROOT,
) -> Path:
    """Return the absolute sources/<project> directory."""
    normalized_project_name = normalize_project_name(project_name)
    return sources_root.resolve() / normalized_project_name


def discover_project_directories(
    sources_root: Path = SOURCES_ROOT,
) -> tuple[Path, ...]:
    """Discover existing sources/<project> directories dynamically."""
    resolved_sources_root = sources_root.resolve()

    if not resolved_sources_root.exists():
        return ()

    if not resolved_sources_root.is_dir():
        raise NotADirectoryError(
            f"Sources root is not a directory: {resolved_sources_root}"
        )

    return tuple(
        sorted(
            (
                project_directory
                for project_directory in resolved_sources_root.iterdir()
                if project_directory.is_dir()
                and not project_directory.name.startswith(".")
            ),
            key=lambda project_directory: (
                project_directory.name.casefold(),
                project_directory.name,
            ),
        )
    )


__all__ = [
    "PROJECT_ROOT",
    "SOURCES_DIR_NAME",
    "SOURCES_ROOT",
    "discover_project_directories",
    "normalize_project_name",
    "resolve_project_directory",
    "resolve_sources_root",
]
