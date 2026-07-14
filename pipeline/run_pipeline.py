"""Run the release pipeline for every discovered crawler output directory."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from pipeline.paths import SOURCES_ROOT

OUTPUT_DIRECTORY_NAME = "output"


def discover_project_output_directories(
    sources_root: Path,
) -> tuple[Path, ...]:
    """Return valid sources/<project>/output directories in stable order."""
    if not sources_root.is_dir():
        raise FileNotFoundError(f"Sources root does not exist: {sources_root}")

    output_directories = tuple(
        project_directory / OUTPUT_DIRECTORY_NAME
        for project_directory in sorted(
            sources_root.iterdir(),
            key=lambda path: path.name.casefold(),
        )
        if project_directory.is_dir()
        and not project_directory.name.startswith(".")
        and (project_directory / OUTPUT_DIRECTORY_NAME).is_dir()
    )

    if not output_directories:
        raise FileNotFoundError(
            f"No crawler output directories found under: {sources_root}"
        )

    return output_directories


def run_project_pipeline(output_directory: Path) -> None:
    """Execute the project pipeline against one crawler output directory."""
    completed_process = subprocess.run(
        [
            sys.executable,
            "-m",
            "pipeline.docs_pipeline_runner",
            str(output_directory),
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
    )

    if completed_process.returncode != 0:
        raise RuntimeError(
            "Project pipeline failed "
            f"with exit code {completed_process.returncode}: "
            f"{output_directory}"
        )


def print_project_header(output_directory: Path) -> None:
    """Print the active project and its resolved crawler output path."""
    project_name = output_directory.parent.name

    print()
    print("=" * 72)
    print(f"PROJECT: {project_name}")
    print(f"OUTPUT:  {output_directory}")
    print("=" * 72)
    print()


def main() -> None:
    """Run the pipeline for every dynamically discovered crawler output."""
    output_directories = discover_project_output_directories(SOURCES_ROOT)

    print("DOCSYNC RELEASE PIPELINE")
    print("========================")
    print(f"Sources root: {SOURCES_ROOT}")

    for output_directory in output_directories:
        print_project_header(output_directory)
        run_project_pipeline(output_directory)

    print()
    print("DOCSYNC RELEASE PIPELINE COMPLETED")
    print("==================================")
    print(f"Projects processed: {len(output_directories)}")


if __name__ == "__main__":
    main()
