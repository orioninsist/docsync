#!/usr/bin/env python3
"""Discover crawler project directories and execute the release pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pipeline.paths import DOCS_PIPELINE_RUNNER, OUTPUT_ROOT, PROJECT_ROOT
from pipeline.subprocess_runner import run_python_script

SEPARATOR_WIDTH = 72


@dataclass(frozen=True, slots=True)
class PipelineSummary:
    """Store aggregate pipeline execution results."""

    processed: int
    succeeded: int
    failed: int

    @property
    def completed_successfully(self) -> bool:
        """Return whether every discovered project succeeded."""
        return self.failed == 0


def contains_direct_markdown(project_directory: Path) -> bool:
    """Return whether a project directory directly contains Markdown files."""
    return any(
        markdown_path.is_file()
        for markdown_path in project_directory.glob("*.md")
    )


def discover_projects() -> list[Path]:
    """Discover sources/<project> directories containing crawler Markdown."""
    if not OUTPUT_ROOT.is_dir():
        return []

    return sorted(
        project_directory
        for project_directory in OUTPUT_ROOT.iterdir()
        if project_directory.is_dir()
        and not project_directory.name.startswith(".")
        and contains_direct_markdown(project_directory)
    )


def print_project_header(project_directory: Path) -> None:
    """Print a visible project execution boundary."""
    print()
    print("=" * SEPARATOR_WIDTH)
    print(f"PROJECT: {project_directory.name}")
    print("=" * SEPARATOR_WIDTH)


def process_project(project_directory: Path) -> bool:
    """Execute the documentation pipeline for one crawler project."""
    print_project_header(project_directory)

    result = run_python_script(
        script=DOCS_PIPELINE_RUNNER,
        args=(str(project_directory),),
    )

    if result == 0:
        print(f"[OK] Pipeline completed: {project_directory.name}")
        return True

    print(f"[FAILED] Pipeline failed: {project_directory.name}")
    return False


def process_projects(projects: list[Path]) -> PipelineSummary:
    """Execute the pipeline independently for every discovered project."""
    succeeded = 0
    failed = 0

    for project_directory in projects:
        if process_project(project_directory):
            succeeded += 1
        else:
            failed += 1

    return PipelineSummary(
        processed=len(projects),
        succeeded=succeeded,
        failed=failed,
    )


def print_summary(summary: PipelineSummary) -> None:
    """Print aggregate pipeline execution results."""
    print()
    print("PIPELINE SUMMARY")
    print("================")
    print(f"Processed: {summary.processed}")
    print(f"Succeeded: {summary.succeeded}")
    print(f"Failed:    {summary.failed}")
    print()


def validate_runtime() -> str | None:
    """Return a runtime validation error or None."""
    if not PROJECT_ROOT.is_dir():
        return f"Project root does not exist: {PROJECT_ROOT}"

    if not OUTPUT_ROOT.is_dir():
        return f"Sources root does not exist: {OUTPUT_ROOT}"

    if not DOCS_PIPELINE_RUNNER.is_file():
        return f"Pipeline runner does not exist: {DOCS_PIPELINE_RUNNER}"

    return None


def main() -> int:
    """Run the documentation release pipeline."""
    print()
    print("DOCSYNC RELEASE PIPELINE")
    print("========================")
    print(f"Sources root: {OUTPUT_ROOT}")

    validation_error = validate_runtime()

    if validation_error is not None:
        print(f"[ERROR] {validation_error}")
        return 1

    projects = discover_projects()

    if not projects:
        print(
            "[ERROR] No crawler project directories containing direct Markdown "
            f"were found under: {OUTPUT_ROOT}"
        )
        return 1

    summary = process_projects(projects)
    print_summary(summary)

    if not summary.completed_successfully:
        return 1

    print("PIPELINE COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
