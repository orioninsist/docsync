#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

from pipeline.file_hash import sha256_file
from pipeline.file_snapshot_repository import FileSnapshot, FileSnapshotRepository
from pipeline.sqlite_connection import sqlite_connection, sqlite_transaction

STATE_DIR_NAME = ".state"
DATABASE_NAME = "incremental.db"
IGNORED_DIR_NAMES = frozenset(
    {
        "_merged",
        "_archive",
        "_raw",
        ".state",
    }
)


def main() -> int:
    project_directory = parse_project_directory(sys.argv)

    if project_directory is None:
        return 2

    validation_error = validate_project_directory(project_directory)

    if validation_error is not None:
        print(validation_error)
        return 1

    return scan_project(project_directory)


def parse_project_directory(arguments: list[str]) -> Path | None:
    if len(arguments) != 2:
        print("Usage: python3 pipeline/incremental_update.py output/project-folder")
        return None

    return Path(arguments[1]).resolve()


def validate_project_directory(project_directory: Path) -> str | None:
    if not project_directory.exists():
        return f"ERROR: Project directory does not exist: {project_directory}"

    if not project_directory.is_dir():
        return f"ERROR: Path is not a directory: {project_directory}"

    return None


def scan_project(project_directory: Path) -> int:
    markdown_files = discover_source_markdown_files(project_directory)

    if not markdown_files:
        print(f"[SKIP] No source markdown files found: {project_directory}")
        return 0

    database_path = resolve_database_path(project_directory)

    with sqlite_connection(database_path) as connection:
        repository = FileSnapshotRepository(connection)
        repository.initialize()
        counts = update_snapshots(
            repository=repository,
            connection=connection,
            project_directory=project_directory,
            markdown_files=markdown_files,
        )

    print_summary(
        project_directory=project_directory,
        database_path=database_path,
        total_files=len(markdown_files),
        counts=counts,
    )

    return 0


def resolve_database_path(project_directory: Path) -> Path:
    return project_directory / STATE_DIR_NAME / DATABASE_NAME


def update_snapshots(
    *,
    repository: FileSnapshotRepository,
    connection: object,
    project_directory: Path,
    markdown_files: list[Path],
) -> dict[str, int]:
    existing_snapshots = index_snapshots(repository.find_all())
    counts = create_status_counts()

    with sqlite_transaction(connection):
        for path in markdown_files:
            status = update_snapshot(
                repository=repository,
                existing_snapshots=existing_snapshots,
                project_directory=project_directory,
                path=path,
            )
            counts[status] += 1
            print(f"[{status.upper()}] {path}")

    return counts


def index_snapshots(
    snapshots: tuple[FileSnapshot, ...],
) -> dict[Path, FileSnapshot]:
    return {snapshot.path: snapshot for snapshot in snapshots}


def create_status_counts() -> dict[str, int]:
    return {
        "new": 0,
        "changed": 0,
        "unchanged": 0,
    }


def update_snapshot(
    *,
    repository: FileSnapshotRepository,
    existing_snapshots: dict[Path, FileSnapshot],
    project_directory: Path,
    path: Path,
) -> str:
    relative_path = path.relative_to(project_directory)
    snapshot = create_snapshot(path=path, relative_path=relative_path)
    existing_snapshot = existing_snapshots.get(relative_path)
    status = classify_snapshot(existing_snapshot, snapshot)

    repository.save(snapshot)
    existing_snapshots[relative_path] = snapshot

    return status


def create_snapshot(*, path: Path, relative_path: Path) -> FileSnapshot:
    file_stat = path.stat()

    return FileSnapshot(
        path=relative_path,
        sha256=sha256_file(path),
        size=file_stat.st_size,
        modified_ns=file_stat.st_mtime_ns,
    )


def classify_snapshot(
    existing_snapshot: FileSnapshot | None,
    current_snapshot: FileSnapshot,
) -> str:
    if existing_snapshot is None:
        return "new"

    if existing_snapshot.sha256 != current_snapshot.sha256:
        return "changed"

    return "unchanged"


def discover_source_markdown_files(project_directory: Path) -> list[Path]:
    return sorted(
        path
        for path in project_directory.rglob("*.md")
        if is_source_markdown(path, project_directory)
    )


def is_source_markdown(path: Path, project_directory: Path) -> bool:
    relative_path = path.relative_to(project_directory)

    if any(part in IGNORED_DIR_NAMES for part in relative_path.parts):
        return False

    if not path.is_file():
        return False

    return path.suffix.lower() == ".md"


def print_summary(
    project_directory: Path,
    database_path: Path,
    total_files: int,
    counts: dict[str, int],
) -> None:
    print()
    print("Incremental Update Summary")
    print("--------------------------")
    print(f"Project: {project_directory}")
    print(f"Total source files: {total_files}")
    print(f"New: {counts['new']}")
    print(f"Changed: {counts['changed']}")
    print(f"Unchanged: {counts['unchanged']}")
    print(f"Ignored directories: {', '.join(sorted(IGNORED_DIR_NAMES))}")
    print(f"State database: {database_path}")


if __name__ == "__main__":
    raise SystemExit(main())
