#!/usr/bin/env python3
"""Orchestrate document processing for one crawler output directory."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from pipeline.document_workspace import (
    READ_ONLY_MODE,
    WRITE_MODE,
    cleanup_legacy_merged_artifacts,
    resolve_project_directory,
    set_markdown_mode,
    validate_markdown_readonly,
)
from pipeline.subprocess_runner import run_python_script

PIPELINE_DIRECTORY = Path(__file__).resolve().parent


class PipelineExecutionError(RuntimeError):
    """Raised when a document pipeline stage cannot be completed."""


@dataclass(frozen=True)
class PipelineStage:
    """Describe one executable document pipeline stage."""

    number: int
    script_name: str
    completion_message: str


PIPELINE_STAGES = (
    PipelineStage(
        number=3,
        script_name="flatten_docs.py",
        completion_message="Flatten stage completed",
    ),
    PipelineStage(
        number=4,
        script_name="incremental_update.py",
        completion_message="Incremental state updated",
    ),
    PipelineStage(
        number=5,
        script_name="merge_service.py",
        completion_message="Merge stage completed",
    ),
)


def parse_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the crawler output directory supplied to the pipeline."""

    parser = argparse.ArgumentParser(
        description="Run the document pipeline for one crawler output directory."
    )
    parser.add_argument(
        "output_directory",
        type=Path,
        help="Crawler output directory to process.",
    )
    return parser.parse_args(arguments)


def resolve_pipeline_script(script_name: str) -> Path:
    """Return an existing pipeline stage script."""

    script_path = PIPELINE_DIRECTORY / script_name

    if not script_path.is_file():
        raise PipelineExecutionError(
            f"Required pipeline script does not exist: {script_path}"
        )

    return script_path


def execute_pipeline_stage(
    stage: PipelineStage,
    project_directory: Path,
) -> None:
    """Execute one pipeline stage and reject unsuccessful completion."""

    script_path = resolve_pipeline_script(stage.script_name)
    return_code = run_python_script(
        script=script_path,
        args=(str(project_directory),),
        cwd=PIPELINE_DIRECTORY.parent,
    )

    if return_code != 0:
        raise PipelineExecutionError(
            f"Pipeline stage failed with exit code {return_code}: "
            f"{stage.script_name}"
        )

    print(f"[{stage.number}/6] {stage.completion_message}")


def execute_pipeline_stages(project_directory: Path) -> None:
    """Execute all configured pipeline stages in declared order."""

    for stage in PIPELINE_STAGES:
        execute_pipeline_stage(stage, project_directory)


def print_pipeline_header(project_directory: Path) -> None:
    """Print the active pipeline workspace."""

    print()
    print("DOCS PIPELINE FINAL RUNNER")
    print("--------------------------")
    print(f"Output directory: {project_directory}")
    print()


def run_document_pipeline(output_directory: Path) -> None:
    """Run the complete document pipeline against one output directory."""

    project_directory = resolve_project_directory(output_directory)
    print_pipeline_header(project_directory)

    unlocked_file_count = set_markdown_mode(
        project_directory,
        WRITE_MODE,
    )
    print(f"[1/6] Unlocked markdown files: {unlocked_file_count}")

    removed_artifact_count = cleanup_legacy_merged_artifacts(
        project_directory
    )
    print(f"[2/6] Removed legacy artifacts: {removed_artifact_count}")

    locked_file_count = 0

    try:
        execute_pipeline_stages(project_directory)
    finally:
        locked_file_count = set_markdown_mode(
            project_directory,
            READ_ONLY_MODE,
        )

    validate_markdown_readonly(project_directory)

    print(f"[6/6] Locked markdown files: {locked_file_count}")
    print("Pipeline completed successfully.")


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the document pipeline CLI."""

    parsed_arguments = parse_arguments(arguments)

    try:
        run_document_pipeline(parsed_arguments.output_directory)
    except (PipelineExecutionError, OSError, ValueError) as error:
        print(f"ERROR: {error}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
