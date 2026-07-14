#!/usr/bin/env python3
"""Build and persist merged Markdown outputs for one crawler output directory."""

from __future__ import annotations

import argparse
import hashlib
from collections.abc import Sequence
from pathlib import Path

from pipeline.merge_engine import MergePlan, MergeSource, create_merge_plan
from pipeline.output_writer import (
    OutputDocument,
    OutputWriteResult,
    synchronize_outputs,
)

UTF8 = "utf-8"
MERGED_DIRECTORY_NAME = "_merged"
CURRENT_DIRECTORY_NAME = "current"
STATE_DIRECTORY_NAME = "state"
IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".state",
        "_archive",
        "_merged",
        "_raw",
    }
)


class MergeServiceError(RuntimeError):
    """Raised when merged Markdown outputs cannot be produced."""


def parse_arguments(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse one crawler output directory from the command line."""
    parser = argparse.ArgumentParser(
        description="Create deterministic merged Markdown outputs."
    )
    parser.add_argument(
        "project_directory",
        type=Path,
        help="Resolved sources/<project_name>/output directory.",
    )
    return parser.parse_args(arguments)


def resolve_project_directory(candidate: Path) -> Path:
    """Resolve and validate one crawler output directory."""
    project_directory = candidate.expanduser().resolve()

    if not project_directory.exists():
        raise MergeServiceError(
            f"Project directory does not exist: {project_directory}"
        )

    if not project_directory.is_dir():
        raise MergeServiceError(
            f"Project path is not a directory: {project_directory}"
        )

    if project_directory.name != "output":
        raise MergeServiceError(
            "Merge input must be a crawler output directory named 'output': "
            f"{project_directory}"
        )

    return project_directory


def discover_markdown_files(project_directory: Path) -> tuple[Path, ...]:
    """Return source Markdown files while excluding pipeline-managed folders."""
    markdown_files: list[Path] = []

    for markdown_file in project_directory.rglob("*.md"):
        if not markdown_file.is_file() or markdown_file.is_symlink():
            continue

        relative_path = markdown_file.relative_to(project_directory)

        if any(
            part in IGNORED_DIRECTORY_NAMES
            for part in relative_path.parts[:-1]
        ):
            continue

        markdown_files.append(markdown_file)

    return tuple(
        sorted(
            markdown_files,
            key=lambda path: (
                path.relative_to(project_directory).as_posix().casefold(),
                path.relative_to(project_directory).as_posix(),
            ),
        )
    )


def read_markdown(path: Path) -> str:
    """Read one UTF-8 Markdown source."""
    try:
        return path.read_text(encoding=UTF8)
    except (OSError, UnicodeError) as error:
        raise MergeServiceError(
            f"Unable to read Markdown source: {path}"
        ) from error


def extract_document_title(content: str, fallback: str) -> str:
    """Return the first Markdown heading or a filename-based fallback."""
    for line in content.splitlines():
        stripped_line = line.strip()

        if not stripped_line.startswith("#"):
            continue

        heading = stripped_line.lstrip("#").strip()

        if heading:
            return heading

    normalized_fallback = fallback.replace("-", " ").replace("_", " ").strip()
    return normalized_fallback or "Untitled Document"


def hash_content(content: str) -> str:
    """Return the SHA-256 fingerprint of UTF-8 Markdown content."""
    return hashlib.sha256(content.encode(UTF8)).hexdigest()


def build_merge_sources(
    project_directory: Path,
    markdown_files: Sequence[Path],
) -> tuple[MergeSource, ...]:
    """Build immutable merge metadata for discovered Markdown files."""
    sources: list[MergeSource] = []

    for markdown_file in markdown_files:
        content = read_markdown(markdown_file)
        relative_path = markdown_file.relative_to(project_directory).as_posix()

        sources.append(
            MergeSource(
                relative_path=relative_path,
                title=extract_document_title(
                    content,
                    markdown_file.stem,
                ),
                fingerprint=hash_content(content),
                size=len(content.encode(UTF8)),
            )
        )

    return tuple(sources)


def build_source_content_index(
    project_directory: Path,
    markdown_files: Sequence[Path],
) -> dict[str, str]:
    """Index source content by normalized relative path."""
    return {
        markdown_file.relative_to(project_directory).as_posix(): read_markdown(
            markdown_file
        )
        for markdown_file in markdown_files
    }


def render_source_section(
    *,
    position: int,
    relative_path: str,
    title: str,
    content: str,
) -> str:
    """Render one source document inside a merged output."""
    normalized_content = content.rstrip()

    return "\n".join(
        (
            f"<!-- source:{relative_path} -->",
            f"## {position}. {title}",
            "",
            normalized_content,
            "",
        )
    )


def render_output_document(
    *,
    project_name: str,
    target_position: int,
    target_count: int,
    source_sections: Sequence[str],
) -> str:
    """Render one deterministic merged Markdown document."""
    header = (
        f"# {project_name} — Merged Documentation"
        if target_count == 1
        else (
            f"# {project_name} — Merged Documentation "
            f"Part {target_position} of {target_count}"
        )
    )

    return "\n".join(
        (
            header,
            "",
            "<!-- generated-by: pipeline.merge_service -->",
            "",
            "\n---\n\n".join(source_sections).rstrip(),
            "",
        )
    )


def build_output_documents(
    plan: MergePlan,
    source_content_by_path: dict[str, str],
) -> tuple[OutputDocument, ...]:
    """Create complete output documents that exactly match the merge plan."""
    documents: list[OutputDocument] = []
    target_count = len(plan.targets)

    for target in plan.targets:
        sections: list[str] = []

        for planned_source in target.sources:
            source = planned_source.source

            try:
                content = source_content_by_path[source.relative_path]
            except KeyError as error:
                raise MergeServiceError(
                    "Merge plan references an unavailable source: "
                    f"{source.relative_path}"
                ) from error

            sections.append(
                render_source_section(
                    position=planned_source.position,
                    relative_path=source.relative_path,
                    title=source.title,
                    content=content,
                )
            )

        documents.append(
            OutputDocument(
                target_name=target.target_name,
                content=render_output_document(
                    project_name=plan.project_name,
                    target_position=target.position,
                    target_count=target_count,
                    source_sections=sections,
                ),
                source_signature=target.source_signature,
            )
        )

    return tuple(documents)


def synchronize_merged_outputs(
    project_directory: Path,
    plan: MergePlan,
    documents: Sequence[OutputDocument],
) -> OutputWriteResult:
    """Persist merged outputs and deterministic writer state."""
    merged_root = project_directory / MERGED_DIRECTORY_NAME

    return synchronize_outputs(
        plan=plan,
        documents=documents,
        output_root=merged_root / CURRENT_DIRECTORY_NAME,
        state_root=merged_root / STATE_DIRECTORY_NAME,
    )


def run_merge_service(project_directory: Path) -> OutputWriteResult:
    """Create, render, and persist merged outputs for one project."""
    markdown_files = discover_markdown_files(project_directory)
    project_name = project_directory.parent.name

    sources = build_merge_sources(
        project_directory,
        markdown_files,
    )
    source_content_by_path = build_source_content_index(
        project_directory,
        markdown_files,
    )
    plan = create_merge_plan(
        project_name=project_name,
        sources=sources,
    )
    documents = build_output_documents(
        plan,
        source_content_by_path,
    )

    return synchronize_merged_outputs(
        project_directory,
        plan,
        documents,
    )


def print_result(
    project_directory: Path,
    result: OutputWriteResult,
) -> None:
    """Print a concise merge synchronization summary."""
    print()
    print("Merge Service Summary")
    print("---------------------")
    print(f"Project: {project_directory}")
    print(f"Written: {len(result.written)}")
    print(f"Unchanged: {len(result.unchanged)}")
    print(f"Removed: {len(result.removed)}")
    print(f"State: {result.state_path}")


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the merge application service from the command line."""
    parsed_arguments = parse_arguments(arguments)

    try:
        project_directory = resolve_project_directory(
            parsed_arguments.project_directory
        )
        result = run_merge_service(project_directory)
    except MergeServiceError as error:
        print(f"ERROR: {error}")
        return 1

    print_result(project_directory, result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
