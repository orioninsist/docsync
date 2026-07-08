#!/usr/bin/env python3
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from pipeline.file_hash import sha256_file

STATE_DIR_NAME = ".state"
DATABASE_NAME = "incremental.db"
IGNORED_DIR_NAMES = {
    "_merged",
    "_archive",
    "_raw",
    ".state",
}


def connect_db(project_dir: Path) -> sqlite3.Connection:
    state_dir = project_dir / STATE_DIR_NAME
    state_dir.mkdir(parents=True, exist_ok=True)
    db_path = state_dir / DATABASE_NAME
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=FULL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=30000;")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS file_snapshots (
            path TEXT PRIMARY KEY,
            sha256 TEXT NOT NULL,
            size INTEGER NOT NULL,
            status TEXT NOT NULL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    conn.commit()
    return conn


def is_source_markdown(path: Path, project_dir: Path) -> bool:
    relative = path.relative_to(project_dir)

    if any(part in IGNORED_DIR_NAMES for part in relative.parts):
        return False

    if not path.is_file():
        return False

    return path.suffix.lower() == ".md"


def discover_source_markdown_files(project_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in project_dir.rglob("*.md")
        if is_source_markdown(path, project_dir)
    )


def scan_project(project_dir: Path) -> int:
    conn = connect_db(project_dir)
    files = discover_source_markdown_files(project_dir)

    if not files:
        print(f"[SKIP] No source markdown files found: {project_dir}")
        conn.close()
        return 0

    new_count = 0
    changed_count = 0
    unchanged_count = 0

    for path in files:
        digest = sha256_file(path)
        size = path.stat().st_size
        key = path.relative_to(project_dir).as_posix()

        existing = conn.execute(
            """
            SELECT sha256
            FROM file_snapshots
            WHERE path = ?
            """,
            (key,),
        ).fetchone()

        if existing is None:
            status = "new"
            new_count += 1
        elif existing["sha256"] != digest:
            status = "changed"
            changed_count += 1
        else:
            status = "unchanged"
            unchanged_count += 1

        conn.execute(
            """
            INSERT INTO file_snapshots(path, sha256, size, status)
            VALUES(?,?,?,?)
            ON CONFLICT(path)
            DO UPDATE SET
                sha256=excluded.sha256,
                size=excluded.size,
                status=excluded.status,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                key,
                digest,
                size,
                status,
            ),
        )

        print(f"[{status.upper()}] {path}")

    conn.commit()
    conn.close()

    print()
    print("Incremental Update Summary")
    print("--------------------------")
    print(f"Project: {project_dir}")
    print(f"Total source files: {len(files)}")
    print(f"New: {new_count}")
    print(f"Changed: {changed_count}")
    print(f"Unchanged: {unchanged_count}")
    print(f"Ignored directories: {', '.join(sorted(IGNORED_DIR_NAMES))}")
    print(f"State database: {project_dir / STATE_DIR_NAME / DATABASE_NAME}")

    return 0


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python3 pipeline/incremental_update.py output/project-folder")
        return 2

    project_dir = Path(sys.argv[1]).resolve()

    if not project_dir.exists():
        print(f"ERROR: Project directory does not exist: {project_dir}")
        return 1

    if not project_dir.is_dir():
        print(f"ERROR: Path is not a directory: {project_dir}")
        return 1

    return scan_project(project_dir)


if __name__ == "__main__":
    raise SystemExit(main())
