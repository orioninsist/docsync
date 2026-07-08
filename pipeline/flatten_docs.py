#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pipeline.file_hash import sha256_file

READ_ONLY_MODE = 0o444
WRITE_MODE = 0o644

IGNORED_DIR_NAMES = {
    "_merged",
    "_archive",
    "_raw",
    ".state",
}

STATE_DIR_NAME = ".state"
DATABASE_NAME = "flatten.db"


@dataclass(frozen=True)
class MovePlan:
    source: Path
    target: Path
    sha256: str
    size: int


def safe_name(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = value.strip("._-")
    return value or "document"


def unlock(path: Path) -> None:
    if path.exists():
        try:
            os.chmod(path, WRITE_MODE)
        except OSError:
            pass


def lock(path: Path) -> None:
    if path.exists():
        try:
            os.chmod(path, READ_ONLY_MODE)
        except OSError:
            pass


def ignored_path(path: Path, project_dir: Path) -> bool:
    relative = path.relative_to(project_dir)
    return any(part in IGNORED_DIR_NAMES for part in relative.parts)


def connect_db(project_dir: Path) -> sqlite3.Connection:
    state_dir = project_dir / STATE_DIR_NAME
    state_dir.mkdir(parents=True, exist_ok=True)
    db_path = state_dir / DATABASE_NAME
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS flattened_files (
            target_path TEXT PRIMARY KEY,
            original_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            size INTEGER NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.commit()
    return conn


def discover_markdown(project_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in project_dir.rglob("*.md")
        if path.is_file() and not ignored_path(path, project_dir)
    )


def build_flat_name(path: Path, project_dir: Path) -> str:
    relative = path.relative_to(project_dir)

    if len(relative.parts) == 1:
        return safe_name(path.name)

    stem_parts = [safe_name(part) for part in relative.with_suffix("").parts]
    return "__".join(stem_parts) + ".md"


def unique_target(path: Path, project_dir: Path, digest: str) -> Path:
    base_name = build_flat_name(path, project_dir)
    target = project_dir / base_name

    if target == path:
        return target

    if not target.exists():
        return target

    if sha256_file(target) == digest:
        return target

    stem = target.stem
    suffix = target.suffix
    return project_dir / f"{stem}__{digest[:12]}{suffix}"


def build_move_plans(project_dir: Path) -> list[MovePlan]:
    plans: list[MovePlan] = []

    for source in discover_markdown(project_dir):
        digest = sha256_file(source)
        target = unique_target(source, project_dir, digest)

        plans.append(
            MovePlan(
                source=source,
                target=target,
                sha256=digest,
                size=source.stat().st_size,
            )
        )

    return plans


def same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def remove_empty_dirs(project_dir: Path) -> int:
    removed = 0

    dirs = sorted(
        [path for path in project_dir.rglob("*") if path.is_dir()],
        key=lambda p: len(p.parts),
        reverse=True,
    )

    for directory in dirs:
        if directory == project_dir:
            continue

        if ignored_path(directory, project_dir):
            continue

        try:
            if not any(directory.iterdir()):
                directory.rmdir()
                removed += 1
        except OSError:
            pass

    return removed


def apply_plans(project_dir: Path, plans: list[MovePlan]) -> tuple[int, int, int]:
    conn = connect_db(project_dir)

    moved = 0
    skipped = 0
    deduped = 0

    for plan in plans:
        if same_file(plan.source, plan.target):
            skipped += 1
            lock(plan.source)
        elif plan.target.exists() and sha256_file(plan.target) == plan.sha256:
            unlock(plan.source)
            try:
                plan.source.unlink()
                deduped += 1
            except OSError:
                skipped += 1
            lock(plan.target)
        else:
            plan.target.parent.mkdir(parents=True, exist_ok=True)
            unlock(plan.source)
            unlock(plan.target)
            shutil.move(str(plan.source), str(plan.target))
            lock(plan.target)
            moved += 1

        relative_target = plan.target.relative_to(project_dir).as_posix()
        relative_source = plan.source.relative_to(project_dir).as_posix()

        conn.execute(
            """
            INSERT INTO flattened_files(target_path, original_path, sha256, size)
            VALUES(?,?,?,?)
            ON CONFLICT(target_path)
            DO UPDATE SET
                original_path=excluded.original_path,
                sha256=excluded.sha256,
                size=excluded.size,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                relative_target,
                relative_source,
                plan.sha256,
                plan.size,
            ),
        )

    conn.commit()
    conn.close()

    return moved, skipped, deduped


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()

    if not project_dir.is_dir():
        print(f"ERROR: Project directory not found: {project_dir}")
        return 1

    plans = build_move_plans(project_dir)

    moved, skipped, deduped = apply_plans(project_dir, plans)
    removed_dirs = remove_empty_dirs(project_dir)

    print()
    print("Flatten Docs Summary")
    print("--------------------")
    print(f"Project: {project_dir}")
    print(f"Markdown files scanned: {len(plans)}")
    print(f"Moved to flat root: {moved}")
    print(f"Already flat / skipped: {skipped}")
    print(f"Duplicate nested files removed: {deduped}")
    print(f"Empty directories removed: {removed_dirs}")
    print(f"State database: {project_dir / STATE_DIR_NAME / DATABASE_NAME}")
    print("Ignored directories: _merged, _archive")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
