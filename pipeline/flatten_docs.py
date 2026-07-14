"""Flatten crawler markdown outputs into a project's output root."""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pipeline.file_hash import sha256_file

RAW_DIRECTORY_NAME = "_raw"
IGNORED_DIR_NAMES = {
    "_merged",
    "_archive",
    ".state",
}
STATE_DIR_NAME = ".state"
DATABASE_NAME = "flatten.db"
READ_ONLY_MODE = 0o444


@dataclass(frozen=True)
class MovePlan:
    """Describe one immutable markdown flattening operation."""

    source: Path
    target: Path
    sha256: str
    size: int


def safe_name(value: str) -> str:
    """Return a filesystem-safe name while preserving readable context."""

    normalized_characters = [
        character if character.isalnum() or character in {"-", "_", "."} else "-"
        for character in value.strip()
    ]
    normalized_name = "".join(normalized_characters)

    while "--" in normalized_name:
        normalized_name = normalized_name.replace("--", "-")

    return normalized_name.strip("-") or "document"


def unlock(path: Path) -> None:
    """Make an existing file writable before replacement or deletion."""

    try:
        os.chmod(path, 0o644)
    except FileNotFoundError:
        return


def lock(path: Path) -> None:
    """Make a generated markdown file strictly read-only."""

    os.chmod(path, READ_ONLY_MODE)


def ignored_path(path: Path, project_dir: Path) -> bool:
    """Return whether a path belongs to a pipeline-owned ignored directory."""

    relative_path = path.relative_to(project_dir)
    return any(part in IGNORED_DIR_NAMES for part in relative_path.parts)


def is_raw_markdown(path: Path, project_dir: Path) -> bool:
    """Return whether a file is a crawler markdown artifact under `_raw`."""

    if not path.is_file() or path.suffix.lower() != ".md":
        return False

    relative_path = path.relative_to(project_dir)

    if RAW_DIRECTORY_NAME not in relative_path.parts:
        return False

    return not ignored_path(path, project_dir)


def connect_db(project_dir: Path) -> sqlite3.Connection:
    """Open the project-local flattening state database."""

    state_dir = project_dir / STATE_DIR_NAME
    state_dir.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(state_dir / DATABASE_NAME)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS flattened_files (
            target_path TEXT PRIMARY KEY,
            original_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            size INTEGER NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_flattened_files_sha256
        ON flattened_files(sha256)
        """
    )
    connection.commit()

    return connection


def discover_markdown(project_dir: Path) -> list[Path]:
    """Discover only crawler markdown files stored beneath `_raw` directories."""

    return sorted(
        path
        for path in project_dir.rglob("*.md")
        if is_raw_markdown(path, project_dir)
    )


def build_flat_name(path: Path, project_dir: Path) -> str:
    """Create a context-aware flat filename from a crawler raw path."""

    relative_path = path.relative_to(project_dir)
    raw_index = relative_path.parts.index(RAW_DIRECTORY_NAME)

    context_parts = relative_path.parts[:raw_index]
    content_hash_parts = relative_path.parts[raw_index + 1 : -1]

    name_parts = [
        safe_name(part)
        for part in (*context_parts, *content_hash_parts)
        if part
    ]

    if not name_parts:
        name_parts.append(safe_name(path.stem))

    return "__".join(name_parts) + ".md"


def unique_target(path: Path, project_dir: Path, digest: str) -> Path:
    """Resolve a deterministic target without overwriting different content."""

    candidate = project_dir / build_flat_name(path, project_dir)

    if not candidate.exists():
        return candidate

    if candidate.is_file() and sha256_file(candidate) == digest:
        return candidate

    return candidate.with_name(
        f"{candidate.stem}__{digest[:12]}{candidate.suffix}"
    )


def build_move_plans(project_dir: Path) -> list[MovePlan]:
    """Build deterministic plans for every raw crawler markdown file."""

    plans: list[MovePlan] = []

    for source_path in discover_markdown(project_dir):
        digest = sha256_file(source_path)
        target_path = unique_target(source_path, project_dir, digest)

        plans.append(
            MovePlan(
                source=source_path,
                target=target_path,
                sha256=digest,
                size=source_path.stat().st_size,
            )
        )

    return plans


def remove_duplicate_source(source: Path) -> None:
    """Delete a raw file whose content already exists at its flat target."""

    unlock(source)
    source.unlink()


def move_source(source: Path, target: Path) -> None:
    """Move one crawler artifact to the flat root and lock it."""

    target.parent.mkdir(parents=True, exist_ok=True)
    unlock(source)
    shutil.move(str(source), str(target))
    lock(target)


def remove_empty_dirs(project_dir: Path) -> int:
    """Remove empty crawler directories while preserving pipeline state areas."""

    removed_count = 0
    directories = sorted(
        (path for path in project_dir.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )

    for directory in directories:
        if directory == project_dir or ignored_path(directory, project_dir):
            continue

        try:
            if any(directory.iterdir()):
                continue

            directory.rmdir()
            removed_count += 1
        except OSError:
            continue

    return removed_count


def record_plan(
    connection: sqlite3.Connection,
    project_dir: Path,
    plan: MovePlan,
) -> None:
    """Persist one completed flattening operation."""

    relative_target = plan.target.relative_to(project_dir).as_posix()
    relative_source = plan.source.relative_to(project_dir).as_posix()

    connection.execute(
        """
        INSERT INTO flattened_files(
            target_path,
            original_path,
            sha256,
            size
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(target_path)
        DO UPDATE SET
            original_path = excluded.original_path,
            sha256 = excluded.sha256,
            size = excluded.size
        """,
        (
            relative_target,
            relative_source,
            plan.sha256,
            plan.size,
        ),
    )


def apply_plans(
    project_dir: Path,
    plans: list[MovePlan],
) -> tuple[int, int, int]:
    """Apply flattening plans with content-based duplicate protection."""

    connection = connect_db(project_dir)
    moved_count = 0
    skipped_count = 0
    deduplicated_count = 0

    try:
        for plan in plans:
            target_exists = plan.target.exists()

            if target_exists and sha256_file(plan.target) == plan.sha256:
                remove_duplicate_source(plan.source)
                lock(plan.target)
                deduplicated_count += 1
            elif target_exists:
                skipped_count += 1
                continue
            else:
                move_source(plan.source, plan.target)
                moved_count += 1

            record_plan(connection, project_dir, plan)

        connection.commit()
    finally:
        connection.close()

    return moved_count, skipped_count, deduplicated_count


def parse_args() -> argparse.Namespace:
    """Parse the project output directory argument."""

    parser = argparse.ArgumentParser(
        description="Flatten crawler markdown files from nested `_raw` directories."
    )
    parser.add_argument(
        "project_dir",
        help="Resolved sources/<project>/output directory.",
    )

    return parser.parse_args()


def main() -> int:
    """Flatten one dynamically resolved crawler output directory."""

    arguments = parse_args()
    project_dir = Path(arguments.project_dir).resolve()

    if not project_dir.exists():
        raise FileNotFoundError(
            f"Project output directory does not exist: {project_dir}"
        )

    if not project_dir.is_dir():
        raise NotADirectoryError(
            f"Project output path is not a directory: {project_dir}"
        )

    plans = build_move_plans(project_dir)
    moved_count, skipped_count, deduplicated_count = apply_plans(
        project_dir,
        plans,
    )
    removed_directory_count = remove_empty_dirs(project_dir)

    print()
    print("Flatten Docs Summary")
    print("--------------------")
    print(f"Project: {project_dir}")
    print(f"Markdown files scanned: {len(plans)}")
    print(f"Moved to flat root: {moved_count}")
    print(f"Already existing / skipped: {skipped_count}")
    print(f"Duplicate nested files removed: {deduplicated_count}")
    print(f"Empty directories removed: {removed_directory_count}")
    print(f"State database: {project_dir / STATE_DIR_NAME / DATABASE_NAME}")
    print(
        "Ignored directories: "
        f"{', '.join(sorted(IGNORED_DIR_NAMES))}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
