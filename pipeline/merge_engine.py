#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pipeline.file_hash import sha256_file
from pipeline.time_utils import utc_now

READ_ONLY_MODE = 0o444
WRITE_MODE = 0o644

MERGED_DIR_NAME = "_merged"
CURRENT_DIR_NAME = "current"
HISTORY_DIR_NAME = "history"
STALE_DIR_NAME = "stale"
STATE_DIR_NAME = ".state"
DATABASE_NAME = "merge.db"

IGNORED_DIR_NAMES = {
    "_merged",
    "_archive",
    "_raw",
    ".state",
    ".git",
    "__pycache__",
}

MAX_FILES_PER_MERGE = 40


@dataclass(frozen=True)
class SourceFile:
    path: Path
    relative_path: str
    sha256: str
    size: int
    title: str
    sort_key: str


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def lock(path: Path) -> None:
    if path.exists():
        os.chmod(path, READ_ONLY_MODE)


def unlock(path: Path) -> None:
    if path.exists():
        os.chmod(path, WRITE_MODE)


def safe_slug(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "merged-docs"


def ignored_path(path: Path, project_dir: Path) -> bool:
    relative = path.relative_to(project_dir)
    return any(part in IGNORED_DIR_NAMES for part in relative.parts)


def discover_markdown_files(project_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in project_dir.rglob("*.md")
        if path.is_file() and not ignored_path(path, project_dir)
    )


def extract_title(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            clean = line.strip()
            if clean.startswith("# "):
                return clean.lstrip("#").strip()
    except OSError:
        pass

    return path.stem.replace("-", " ").replace("_", " ").strip().title() or "Untitled"


def load_sources(project_dir: Path) -> list[SourceFile]:
    sources: list[SourceFile] = []

    for path in discover_markdown_files(project_dir):
        relative = path.relative_to(project_dir).as_posix()
        digest = sha256_file(path)

        sources.append(
            SourceFile(
                path=path,
                relative_path=relative,
                sha256=digest,
                size=path.stat().st_size,
                title=extract_title(path),
                sort_key=relative.lower(),
            )
        )

    return sorted(sources, key=lambda item: item.sort_key)


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

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS merge_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_dir TEXT NOT NULL,
            source_count INTEGER NOT NULL,
            merged_count INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS merged_files (
            filename TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL,
            source_signature TEXT NOT NULL,
            source_count INTEGER NOT NULL,
            size INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS merged_sources (
            filename TEXT NOT NULL,
            source_path TEXT NOT NULL,
            source_sha256 TEXT NOT NULL,
            source_size INTEGER NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(filename, source_path)
        );
        """
    )

    conn.commit()
    return conn


def chunk_sources(sources: list[SourceFile]) -> list[list[SourceFile]]:
    return [
        sources[index : index + MAX_FILES_PER_MERGE]
        for index in range(0, len(sources), MAX_FILES_PER_MERGE)
    ]


def build_group_name(
    project_dir: Path, group_index: int, total_groups: int, group: list[SourceFile]
) -> str:
    project_slug = safe_slug(project_dir.name)

    if total_groups == 1:
        return f"{project_slug}__merged.md"

    first_title = safe_slug(group[0].title)[:40]
    return f"{project_slug}__part-{group_index:03d}__{first_title}.md"


def build_source_signature(group: list[SourceFile]) -> str:
    raw = "\n".join(
        f"{source.relative_path}\t{source.sha256}\t{source.size}" for source in group
    )
    return sha256_text(raw)


def read_source_body(source: SourceFile) -> str:
    return source.path.read_text(encoding="utf-8", errors="replace").strip()


def build_merged_document(
    project_dir: Path, filename: str, group: list[SourceFile]
) -> str:
    lines: list[str] = []

    lines.append(f"# {project_dir.name} merged documentation")
    lines.append("")
    lines.append(f"Generated file: `{filename}`")
    lines.append("Generated by: `docsync merge_engine`")
    lines.append(f"Source files: `{len(group)}`")
    lines.append("")
    lines.append("<!--")
    lines.append("This file is generated by docsync.")
    lines.append("Do not edit manually. The pipeline will lock it as read-only.")
    lines.append("-->")
    lines.append("")
    lines.append("## Source Index")
    lines.append("")

    for index, source in enumerate(group, start=1):
        lines.append(f"{index}. `{source.relative_path}` - `{source.sha256}`")

    lines.append("")

    for index, source in enumerate(group, start=1):
        lines.append("---")
        lines.append("")
        lines.append(f"## Source {index}: {source.title}")
        lines.append("")
        lines.append(f"Source path: `{source.relative_path}`")
        lines.append(f"Source sha256: `{source.sha256}`")
        lines.append("")
        lines.append(read_source_body(source))
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_if_changed(path: Path, content: str) -> tuple[bool, str]:
    content_hash = sha256_text(content)

    if path.exists():
        existing = path.read_text(encoding="utf-8", errors="replace")
        if sha256_text(existing) == content_hash:
            lock(path)
            return False, content_hash

    path.parent.mkdir(parents=True, exist_ok=True)
    unlock(path)
    path.write_text(content, encoding="utf-8")
    lock(path)
    return True, content_hash


def archive_old_version(
    current_path: Path, history_dir: Path, old_hash: str
) -> Path | None:
    if not current_path.exists():
        return None

    history_dir.mkdir(parents=True, exist_ok=True)
    archive_path = history_dir / f"{current_path.stem}__{old_hash[:16]}.md"

    if archive_path.exists():
        lock(archive_path)
        return archive_path

    unlock(current_path)
    archive_path.write_text(
        current_path.read_text(encoding="utf-8", errors="replace"),
        encoding="utf-8",
    )
    lock(archive_path)
    return archive_path


def move_stale_current_files(
    current_dir: Path,
    stale_dir: Path,
    expected_names: set[str],
) -> int:
    moved = 0

    if not current_dir.exists():
        return moved

    stale_dir.mkdir(parents=True, exist_ok=True)

    for path in current_dir.glob("*.md"):
        if path.name in expected_names:
            continue

        unlock(path)

        target = stale_dir / path.name

        if target.exists():
            target_hash = sha256_file(target)
            source_hash = sha256_file(path)

            if target_hash == source_hash:
                path.unlink()
                lock(target)
            else:
                target = stale_dir / f"{path.stem}__{source_hash[:16]}{path.suffix}"
                path.rename(target)
                lock(target)
        else:
            path.rename(target)
            lock(target)

        moved += 1

    return moved


def update_database(
    conn: sqlite3.Connection,
    filename: str,
    content_hash: str,
    source_signature: str,
    group: list[SourceFile],
    output_path: Path,
) -> None:
    now = utc_now()

    conn.execute(
        """
        INSERT INTO merged_files (
            filename,
            content_hash,
            source_signature,
            source_count,
            size,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(filename)
        DO UPDATE SET
            content_hash = excluded.content_hash,
            source_signature = excluded.source_signature,
            source_count = excluded.source_count,
            size = excluded.size,
            updated_at = excluded.updated_at;
        """,
        (
            filename,
            content_hash,
            source_signature,
            len(group),
            output_path.stat().st_size,
            now,
        ),
    )

    conn.execute(
        "DELETE FROM merged_sources WHERE filename = ?;",
        (filename,),
    )

    for source in group:
        conn.execute(
            """
            INSERT INTO merged_sources (
                filename,
                source_path,
                source_sha256,
                source_size,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?);
            """,
            (
                filename,
                source.relative_path,
                source.sha256,
                source.size,
                now,
            ),
        )


def run_merge(project_dir: Path) -> int:
    sources = load_sources(project_dir)

    if not sources:
        print(f"[SKIP] No markdown files found: {project_dir}")
        return 0

    merged_root = project_dir / MERGED_DIR_NAME
    current_dir = merged_root / CURRENT_DIR_NAME
    history_dir = merged_root / HISTORY_DIR_NAME
    stale_dir = merged_root / STALE_DIR_NAME

    groups = chunk_sources(sources)
    total_groups = len(groups)

    conn = connect_db(project_dir)

    created_or_updated = 0
    unchanged = 0
    archived = 0
    expected_names: set[str] = set()

    try:
        conn.execute("BEGIN IMMEDIATE;")

        for index, group in enumerate(groups, start=1):
            filename = build_group_name(project_dir, index, total_groups, group)
            expected_names.add(filename)

            output_path = current_dir / filename
            source_signature = build_source_signature(group)
            content = build_merged_document(project_dir, filename, group)
            new_hash = sha256_text(content)

            existing = conn.execute(
                """
                SELECT content_hash
                FROM merged_files
                WHERE filename = ?
                LIMIT 1;
                """,
                (filename,),
            ).fetchone()

            if (
                existing is not None
                and existing["content_hash"] != new_hash
                and output_path.exists()
            ):
                archive_old_version(
                    output_path, history_dir, str(existing["content_hash"])
                )
                archived += 1

            changed, content_hash = write_if_changed(output_path, content)

            if changed:
                created_or_updated += 1
            else:
                unchanged += 1

            update_database(
                conn=conn,
                filename=filename,
                content_hash=content_hash,
                source_signature=source_signature,
                group=group,
                output_path=output_path,
            )

        stale_moved = move_stale_current_files(
            current_dir=current_dir,
            stale_dir=stale_dir,
            expected_names=expected_names,
        )

        conn.execute(
            """
            INSERT INTO merge_runs (
                project_dir,
                source_count,
                merged_count,
                created_at
            )
            VALUES (?, ?, ?, ?);
            """,
            (
                project_dir.as_posix(),
                len(sources),
                total_groups,
                utc_now(),
            ),
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    for md_file in merged_root.rglob("*.md"):
        lock(md_file)

    print()
    print("Merge Engine Summary")
    print("--------------------")
    print(f"Project: {project_dir}")
    print(f"Source files: {len(sources)}")
    print(f"Merged files: {total_groups}")
    print(f"Created/updated: {created_or_updated}")
    print(f"Unchanged: {unchanged}")
    print(f"Archived old versions: {archived}")
    print(f"Moved stale current files: {stale_moved}")
    print(f"Current output: {current_dir}")
    print(f"History output: {history_dir}")
    print(f"Stale output: {stale_dir}")
    print(f"State database: {project_dir / STATE_DIR_NAME / DATABASE_NAME}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stable, idempotent Markdown merge engine for docsync."
    )
    parser.add_argument("project_dir")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()

    if not project_dir.is_dir():
        print(f"ERROR: Project directory not found: {project_dir}")
        return 1

    return run_merge(project_dir)


if __name__ == "__main__":
    raise SystemExit(main())
