"""Resolve DOCSYNC project paths without static project assumptions."""

from __future__ import annotations

from pathlib import Path
from typing import Final

OUTPUT_DIR_NAME: Final = "output"
SOURCES_DIR_NAME: Final = "sources"

PROJECT_ROOT: Final = Path(__file__).resolve().parent.parent
SOURCES_ROOT: Final = PROJECT_ROOT / SOURCES_DIR_NAME


def resolve_sources_root(project_root: Path = PROJECT_ROOT) -> Path:
    """Return the absolute sources directory for a project root."""
    return project_root.resolve() / SOURCES_DIR_NAME


def resolve_project_output_directory(
    project_name: str,
    sources_root: Path = SOURCES_ROOT,
) -> Path:
    """Return the absolute output directory for one source project."""
    normalized_project_name = project_name.strip()

    if not normalized_project_name:
        raise ValueError("Project name must not be empty.")

    if Path(normalized_project_name).name != normalized_project_name:
        raise ValueError(
            "Project name must be a single directory name without path separators."
        )

    return sources_root.resolve() / normalized_project_name / OUTPUT_DIR_NAME


def discover_project_output_directories(
    sources_root: Path = SOURCES_ROOT,
) -> tuple[Path, ...]:
    """Discover existing sources/<project>/output directories dynamically."""
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
                project_directory / OUTPUT_DIR_NAME
                for project_directory in resolved_sources_root.iterdir()
                if project_directory.is_dir()
                and (project_directory / OUTPUT_DIR_NAME).is_dir()
            ),
            key=lambda output_directory: output_directory.parent.name.casefold(),
        )
    )
