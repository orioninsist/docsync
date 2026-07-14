"""Shared filesystem paths for the independent pipeline system."""

from __future__ import annotations

import os
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PIPELINE_ROOT.parent

DEFAULT_SOURCES_ROOT = PROJECT_ROOT / "sources"

SOURCES_ROOT = Path(
    os.environ.get("DOCSYNC_SOURCES_ROOT", DEFAULT_SOURCES_ROOT)
).expanduser().resolve()

OUTPUT_DIR_NAME = "output"
DOCS_PIPELINE_RUNNER = PIPELINE_ROOT / "docs_pipeline_runner.py"


def normalize_project_name(project_name: str) -> str:
    """Return a safe project directory name."""

    normalized_name = project_name.strip()

    if not normalized_name:
        raise ValueError("Project name cannot be empty.")

    if normalized_name in {".", ".."}:
        raise ValueError(f"Invalid project name: {project_name!r}")

    if Path(normalized_name).name != normalized_name:
        raise ValueError(
            "Project name must not contain directory separators: "
            f"{project_name!r}"
        )

    return normalized_name


def project_directory(project_name: str) -> Path:
    """Return sources/<project> for the requested project."""

    normalized_name = normalize_project_name(project_name)
    return SOURCES_ROOT / normalized_name


def project_output_directory(project_name: str) -> Path:
    """Return sources/<project>/output for the requested project."""

    return project_directory(project_name) / OUTPUT_DIR_NAME


def discover_project_output_directories(
    *,
    require_markdown: bool = False,
) -> tuple[Path, ...]:
    """Discover existing sources/<project>/output directories.

    Args:
        require_markdown:
            When true, return only output directories containing at least one
            Markdown file.

    Returns:
        Absolute output directory paths sorted by project name.
    """

    if not SOURCES_ROOT.is_dir():
        return ()

    output_directories: list[Path] = []

    for project_dir in sorted(
        SOURCES_ROOT.iterdir(),
        key=lambda path: path.name.casefold(),
    ):
        if not project_dir.is_dir():
            continue

        output_dir = project_dir / OUTPUT_DIR_NAME

        if not output_dir.is_dir():
            continue

        if require_markdown and not any(output_dir.rglob("*.md")):
            continue

        output_directories.append(output_dir.resolve())

    return tuple(output_directories)


__all__ = [
    "DEFAULT_SOURCES_ROOT",
    "DOCS_PIPELINE_RUNNER",
    "OUTPUT_DIR_NAME",
    "PIPELINE_ROOT",
    "PROJECT_ROOT",
    "SOURCES_ROOT",
    "discover_project_output_directories",
    "normalize_project_name",
    "project_directory",
    "project_output_directory",
]
