#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import stat
from pathlib import Path

from pipeline.subprocess_runner import run_python_script

READ_ONLY_MODE = 0o444
WRITE_MODE = 0o644

MERGED_DIR_NAME = "_merged"
MERGED_ALLOWED_DIRS = {"current", "history", "stale"}
LEGACY_MERGE_DB_NAME = ".merge_state.db"


def unlock_markdown_files(project_dir: Path) -> int:
    count = 0
    for md_file in project_dir.rglob("*.md"):
        try:
            os.chmod(md_file, WRITE_MODE)
            count += 1
        except OSError:
            pass
    return count


def lock_markdown_files(project_dir: Path) -> int:
    count = 0
    for md_file in project_dir.rglob("*.md"):
        try:
            os.chmod(md_file, READ_ONLY_MODE)
            count += 1
        except OSError:
            pass
    return count


def cleanup_legacy_merged_artifacts(project_dir: Path) -> int:
    merged_dir = project_dir / MERGED_DIR_NAME
    removed = 0

    if not merged_dir.exists():
        return removed

    legacy_db = merged_dir / LEGACY_MERGE_DB_NAME
    if legacy_db.exists() and legacy_db.is_file():
        try:
            legacy_db.unlink()
            removed += 1
        except OSError:
            pass

    for item in merged_dir.iterdir():
        if item.is_dir() and item.name in MERGED_ALLOWED_DIRS:
            continue

        if item.is_file() and item.suffix.lower() == ".md":
            try:
                os.chmod(item, WRITE_MODE)
            except OSError:
                pass

            try:
                item.unlink()
                removed += 1
            except OSError:
                pass

    return removed


def run_script(script_name: str, project_dir: Path) -> int:
    script = Path(__file__).resolve().parent / script_name

    if not script.exists():
        print(f"[ERROR] Missing pipeline script: {script}")
        return 1

    return run_python_script(script=script, args=(str(project_dir),))


def validate_readonly(project_dir: Path) -> bool:
    for md_file in project_dir.rglob("*.md"):
        mode = stat.S_IMODE(md_file.stat().st_mode)
        if mode != READ_ONLY_MODE:
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir")
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve()

    if not project_dir.exists():
        print(f"ERROR: Project directory not found: {project_dir}")
        return 1

    if not project_dir.is_dir():
        print(f"ERROR: Path is not a directory: {project_dir}")
        return 1

    print()
    print("DOCS PIPELINE FINAL RUNNER")
    print("--------------------------")

    unlocked = unlock_markdown_files(project_dir)
    print(f"[1/6] Unlocked markdown files: {unlocked}")

    removed_legacy = cleanup_legacy_merged_artifacts(project_dir)
    print(f"[2/6] Removed legacy artifacts: {removed_legacy}")

    flatten_result = run_script("flatten_docs.py", project_dir)
    if flatten_result != 0:
        print("[ERROR] Flatten stage failed.")
        return flatten_result
    print("[3/6] Flatten stage completed")

    incremental_result = run_script("incremental_update.py", project_dir)
    if incremental_result != 0:
        print("[ERROR] Incremental state stage failed.")
        return incremental_result
    print("[4/6] Incremental state updated")

    merge_result = run_script("merge_engine.py", project_dir)
    if merge_result != 0:
        print("[ERROR] Merge stage failed.")
        return merge_result
    print("[5/6] Merge stage completed")

    removed_after_merge = cleanup_legacy_merged_artifacts(project_dir)
    if removed_after_merge:
        print(f"[CLEANUP] Removed post-merge legacy artifacts: {removed_after_merge}")

    locked = lock_markdown_files(project_dir)
    print(f"[6/6] Locked markdown files: {locked}")

    if not validate_readonly(project_dir):
        print("ERROR: Read-only validation failed.")
        return 1

    print("Pipeline completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
