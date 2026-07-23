"""Flatten crawler Markdown outputs into one project output root."""

from __future__ import annotations

import argparse
import os
import re
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pipeline.constants import (
    FLATTEN_DATABASE_NAME,
    IGNORED_DIRECTORY_NAMES,
    READ_ONLY_MODE,
    STATE_DIRECTORY_NAME,
    WRITE_MODE,
)
from pipeline.file_hash import sha256_file
from pipeline.flattened_file_repository import (
    FlattenedFileRepository,
    create_flattened_file_record,
)
from pipeline.sqlite_connection import sqlite_connection, sqlite_transaction


class FlattenArguments(argparse.Namespace):
    """Typed command-line arguments for the flattening command."""

    project_dir: str = ""


@dataclass(frozen=True, slots=True)
class MovePlan:
    """Describe one deterministic Markdown flattening operation."""

    source: Path
    target: Path
    sha256: str
    size: int


@dataclass(frozen=True, slots=True)
class FlattenResult:
    """Aggregate counters produced by one flattening execution."""

    moved: int
    skipped: int
    deduplicated: int


def parse_arguments(arguments: Sequence[str] | None = None) -> FlattenArguments:
    """Parse the project output directory argument."""

    parser = argparse.ArgumentParser(
        description="Flatten nested Markdown files into one output directory."
    )
    _ = parser.add_argument(
        "project_dir",
        help="Resolved sources/<project>/output directory.",
    )
    return parser.parse_args(arguments, namespace=FlattenArguments())


def run_flatten(project_dir: Path) -> FlattenResult:
    """Flatten one dynamically resolved crawler output directory."""

    plans = build_move_plans(project_dir)
    database = project_dir / STATE_DIRECTORY_NAME / FLATTEN_DATABASE_NAME

    with sqlite_connection(database) as connection:
        repository = FlattenedFileRepository(connection)
        repository.initialize()

        with sqlite_transaction(connection):
            return apply_plans(
                project_dir=project_dir,
                plans=plans,
                repository=repository,
            )


def build_move_plans(project_dir: Path) -> tuple[MovePlan, ...]:
    """Create immutable movement plans for every eligible Markdown file."""

    return tuple(
        create_move_plan(source_path, project_dir)
        for source_path in discover_markdown(project_dir)
    )


def create_move_plan(source_path: Path, project_dir: Path) -> MovePlan:
    """Create one deterministic movement plan."""

    digest = sha256_file(source_path)

    return MovePlan(
        source=source_path,
        target=unique_target(source_path, project_dir, digest),
        sha256=digest,
        size=source_path.stat().st_size,
    )


def discover_markdown(project_dir: Path) -> tuple[Path, ...]:
    """Return eligible Markdown files in deterministic order."""

    return tuple(
        path
        for path in sorted(project_dir.rglob("*.md"))
        if path.is_file() and not ignored_path(path, project_dir)
    )


def ignored_path(path: Path, project_dir: Path) -> bool:
    """Return whether a path belongs to an ignored pipeline directory."""

    relative_path = path.relative_to(project_dir)
    return any(part in IGNORED_DIRECTORY_NAMES for part in relative_path.parts)


def unique_target(path: Path, project_dir: Path, digest: str) -> Path:
    """Resolve a collision-safe flat target for one Markdown source."""

    target = project_dir / build_flat_name(path, project_dir)

    if target == path:
        return target

    if not target.exists():
        return target

    if files_match(path, target):
        return target

    return target.with_name(f"{target.stem}__{digest[:12]}{target.suffix}")


def build_flat_name(path: Path, project_dir: Path) -> str:
    """Build a deterministic flat Markdown filename."""

    relative_path = path.relative_to(project_dir)

    if len(relative_path.parts) == 1:
        return safe_name(path.name)

    stem_parts = tuple(safe_name(part) for part in relative_path.with_suffix("").parts)
    return "__".join(stem_parts) + ".md"


def safe_name(value: str) -> str:
    """Normalize one path component for a flat filename."""

    normalized = value.strip().replace(" ", "-")
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized)
    normalized = normalized.strip("-._")

    return normalized or "document"


def files_match(left: Path, right: Path) -> bool:
    """Return whether two files contain identical bytes."""

    try:
        return left.stat().st_size == right.stat().st_size and (
            sha256_file(left) == sha256_file(right)
        )
    except OSError:
        return False


def apply_plans(
    *,
    project_dir: Path,
    plans: Sequence[MovePlan],
    repository: FlattenedFileRepository,
) -> FlattenResult:
    """Apply filesystem plans and persist their resulting state."""

    moved = 0
    skipped = 0
    deduplicated = 0

    for plan in plans:
        outcome = apply_plan(plan)

        if outcome == "moved":
            moved += 1
        elif outcome == "deduplicated":
            deduplicated += 1
        else:
            skipped += 1

        persist_plan(
            repository=repository,
            project_dir=project_dir,
            plan=plan,
        )

    return FlattenResult(
        moved=moved,
        skipped=skipped,
        deduplicated=deduplicated,
    )


def apply_plan(plan: MovePlan) -> str:
    """Apply one movement plan and return its stable outcome."""

    if plan.source == plan.target:
        lock(plan.target)
        return "skipped"

    if plan.target.exists() and files_match(plan.source, plan.target):
        remove_duplicate_source(plan.source)
        lock(plan.target)
        return "deduplicated"

    move_source(plan.source, plan.target)
    lock(plan.target)
    return "moved"


def remove_duplicate_source(source: Path) -> None:
    """Delete one nested source already represented by its target."""

    unlock(source)
    source.unlink()


def move_source(source: Path, target: Path) -> None:
    """Move one source to its planned flat target."""

    target.parent.mkdir(parents=True, exist_ok=True)
    unlock(source)
    _ = shutil.move(str(source), str(target))


def persist_plan(
    *,
    repository: FlattenedFileRepository,
    project_dir: Path,
    plan: MovePlan,
) -> None:
    """Persist the final state represented by one movement plan."""

    record = create_flattened_file_record(
        project_directory=project_dir,
        target_path=plan.target,
        source_path=plan.source,
        sha256=plan.sha256,
        size=plan.size,
    )
    repository.save(record)


def remove_empty_dirs(project_dir: Path) -> int:
    """Remove empty non-pipeline directories below the project output."""

    removed = 0

    directories = sorted(
        (path for path in project_dir.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )

    for directory in directories:
        if directory == project_dir:
            continue

        if ignored_path(directory, project_dir):
            continue

        try:
            if any(directory.iterdir()):
                continue

            directory.rmdir()
            removed += 1
        except OSError:
            continue

    return removed


def unlock(path: Path) -> None:
    """Make an existing path writable when possible."""

    if not path.exists():
        return

    try:
        os.chmod(path, WRITE_MODE)
    except OSError:
        return


def lock(path: Path) -> None:
    """Make an existing Markdown file read-only when possible."""

    if not path.exists():
        return

    try:
        os.chmod(path, READ_ONLY_MODE)
    except OSError:
        return


def validate_project_directory(project_dir: Path) -> None:
    """Reject invalid project output paths."""

    if not project_dir.exists():
        raise FileNotFoundError(
            f"Project output directory does not exist: {project_dir}"
        )

    if not project_dir.is_dir():
        raise NotADirectoryError(
            f"Project output path is not a directory: {project_dir}"
        )


def print_summary(
    *,
    project_dir: Path,
    scanned: int,
    result: FlattenResult,
    removed_directories: int,
) -> None:
    """Print the deterministic flattening summary."""

    database_path = project_dir / STATE_DIRECTORY_NAME / FLATTEN_DATABASE_NAME

    print()
    print("Flatten Docs Summary")
    print("--------------------")
    print(f"Project: {project_dir}")
    print(f"Markdown files scanned: {scanned}")
    print(f"Moved to flat root: {result.moved}")
    print(f"Already flat / skipped: {result.skipped}")
    print(f"Duplicate nested files removed: {result.deduplicated}")
    print(f"Empty directories removed: {removed_directories}")
    print(f"State database: {database_path}")
    print(f"Ignored directories: {', '.join(sorted(IGNORED_DIRECTORY_NAMES))}")


def main(arguments: Sequence[str] | None = None) -> int:
    """Run the flattening command."""

    parsed_arguments = parse_arguments(arguments)
    project_dir = Path(parsed_arguments.project_dir).resolve()

    try:
        validate_project_directory(project_dir)
    except (FileNotFoundError, NotADirectoryError) as error:
        print(f"ERROR: {error}")
        return 1

    plans = build_move_plans(project_dir)
    result = run_flatten(project_dir)
    removed_directories = remove_empty_dirs(project_dir)

    print_summary(
        project_dir=project_dir,
        scanned=len(plans),
        result=result,
        removed_directories=removed_directories,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
