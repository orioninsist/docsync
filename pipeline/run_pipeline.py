"""Run the document pipeline for every discovered source project directory."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from pipeline.paths import (
    PROJECT_ROOT,
    SOURCES_ROOT,
    discover_project_directories,
)
from pipeline.subprocess_runner import run_command

SECTION_WIDTH = 72
PIPELINE_RUNNER_MODULE = "pipeline.docs_pipeline_runner"


def run_project_pipeline(project_directory: Path) -> None:
    """Run the document pipeline for one source project directory."""
    _ = run_command(
        [
            sys.executable,
            "-m",
            PIPELINE_RUNNER_MODULE,
            str(project_directory),
        ],
        cwd=PROJECT_ROOT,
    )


def print_release_header() -> None:
    """Print the release pipeline header and resolved sources root."""
    print("DOCSYNC RELEASE PIPELINE")
    print("========================")
    print(f"Sources root: {SOURCES_ROOT.resolve()}")


def print_project_header(project_directory: Path) -> None:
    """Print the project identity and resolved source directory."""
    print()
    print("=" * SECTION_WIDTH)
    print(f"PROJECT: {project_directory.name}")
    print(f"SOURCE:  {project_directory}")
    print("=" * SECTION_WIDTH)
    print()


def print_release_summary(project_count: int) -> None:
    """Print the successful release pipeline summary."""
    print()
    print("DOCSYNC RELEASE PIPELINE COMPLETED")
    print("==================================")
    print(f"Projects processed: {project_count}")


def require_discovered_projects(
    project_directories: Sequence[Path],
) -> None:
    """Raise an error when no source project directories are available."""
    if not project_directories:
        raise FileNotFoundError(
            f"No source project directories found under {SOURCES_ROOT.resolve()}."
        )


def run_release_pipeline(project_directories: Sequence[Path]) -> None:
    """Run the release pipeline for all discovered source projects."""
    require_discovered_projects(project_directories)
    print_release_header()

    for project_directory in project_directories:
        print_project_header(project_directory)
        run_project_pipeline(project_directory)

    print_release_summary(len(project_directories))


def main() -> None:
    """Discover source projects and start the release pipeline."""
    project_directories = discover_project_directories()
    run_release_pipeline(project_directories)


if __name__ == "__main__":
    main()
