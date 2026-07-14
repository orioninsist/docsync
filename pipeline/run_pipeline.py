"""Run the document pipeline for every discovered crawler output directory."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

from pipeline.paths import (
    PROJECT_ROOT,
    SOURCES_ROOT,
    discover_project_output_directories,
)
from pipeline.subprocess_runner import run_command

SECTION_WIDTH = 72
PIPELINE_RUNNER_MODULE = "pipeline.docs_pipeline_runner"


def run_project_pipeline(output_directory: Path) -> None:
    """Run the document pipeline for one crawler output directory."""
    run_command(
        [
            sys.executable,
            "-m",
            PIPELINE_RUNNER_MODULE,
            str(output_directory),
        ],
        cwd=PROJECT_ROOT,
    )


def print_release_header() -> None:
    """Print the release pipeline header and dynamically resolved source root."""
    print("DOCSYNC RELEASE PIPELINE")
    print("========================")
    print(f"Sources root: {SOURCES_ROOT.resolve()}")


def print_project_header(output_directory: Path) -> None:
    """Print the project identity and its resolved crawler output directory."""
    print()
    print("=" * SECTION_WIDTH)
    print(f"PROJECT: {output_directory.parent.name}")
    print(f"OUTPUT:  {output_directory}")
    print("=" * SECTION_WIDTH)
    print()


def print_release_summary(project_count: int) -> None:
    """Print the successful release pipeline summary."""
    print()
    print("DOCSYNC RELEASE PIPELINE COMPLETED")
    print("==================================")
    print(f"Projects processed: {project_count}")


def require_discovered_outputs(
    output_directories: Sequence[Path],
) -> None:
    """Raise an error when no crawler output directories are available."""
    if not output_directories:
        raise FileNotFoundError(
            f"No crawler output directories found under {SOURCES_ROOT.resolve()}."
        )


def run_release_pipeline(output_directories: Sequence[Path]) -> None:
    """Run the release pipeline for all discovered crawler outputs."""
    require_discovered_outputs(output_directories)
    print_release_header()

    for output_directory in output_directories:
        print_project_header(output_directory)
        run_project_pipeline(output_directory)

    print_release_summary(len(output_directories))


def main() -> None:
    """Discover crawler outputs and start the release pipeline."""
    output_directories = tuple(discover_project_output_directories())
    run_release_pipeline(output_directories)


if __name__ == "__main__":
    main()
