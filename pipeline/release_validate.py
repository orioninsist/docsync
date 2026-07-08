#!/usr/bin/env python3
from __future__ import annotations

import stat
import sys
from pathlib import Path

from pipeline.paths import OUTPUT_ROOT, PROJECT_ROOT, STATE_ROOT
from pipeline.subprocess_runner import run_command

FORBIDDEN_PATHS = [
    PROJECT_ROOT / "pipeline" / "incremental_state.db",
    STATE_ROOT / "global_url_registry.db",
]

REQUIRED_FILES = [
    PROJECT_ROOT / "crawler" / "crawler_engine.py",
    PROJECT_ROOT / "crawler" / "markdown_writer.py",
    PROJECT_ROOT / "pipeline" / "run_pipeline.py",
    PROJECT_ROOT / "pipeline" / "docs_pipeline_runner.py",
    PROJECT_ROOT / "pipeline" / "flatten_docs.py",
    PROJECT_ROOT / "pipeline" / "incremental_update.py",
    PROJECT_ROOT / "pipeline" / "merge_engine.py",
    PROJECT_ROOT / "pipeline" / "global_url_registry.py",
]

IGNORED_SOURCE_DIR_NAMES = {
    "_merged",
    "_archive",
    "_raw",
    ".state",
    ".git",
    "__pycache__",
}

READ_ONLY_MODE = 0o444


def run(command: list[str]) -> int:
    print()
    print("$ " + " ".join(command))
    return run_command(command, cwd=PROJECT_ROOT)


def fail(message: str) -> int:
    print(f"[FAIL] {message}")
    return 1


def check_required_files() -> int:
    missing = [path for path in REQUIRED_FILES if not path.is_file()]

    if missing:
        for path in missing:
            print(f"[MISSING] {path}")
        return fail("Required release files are missing.")

    print("[OK] Required files exist.")
    return 0


def check_forbidden_paths() -> int:
    bad = [path for path in FORBIDDEN_PATHS if path.exists()]

    if bad:
        for path in bad:
            print(f"[FORBIDDEN] {path}")
        return fail("Forbidden legacy state paths still exist.")

    print("[OK] Forbidden legacy state paths are absent.")
    return 0


def check_pycache_absent() -> int:
    excluded_roots = {
        ".venv",
        "venv",
        "output",
        "state",
        "logs",
        ".git",
    }

    pycache_dirs = [
        p
        for p in sorted(PROJECT_ROOT.rglob("__pycache__"))
        if not any(part in excluded_roots for part in p.parts)
    ]

    for path in pycache_dirs:
        try:
            for item in path.rglob("*"):
                if item.is_file():
                    item.unlink()
            path.rmdir()
            print(f"[CLEANED PYCACHE] {path}")
        except OSError:
            return fail(f"Could not remove __pycache__: {path}")

    print("[OK] __pycache__ directories cleaned.")
    return 0


def compile_python() -> int:
    python_files = [
        str(path.relative_to(PROJECT_ROOT))
        for path in sorted(PROJECT_ROOT.rglob("*.py"))
        if ".git" not in path.parts
        and ".venv" not in path.parts
        and "venv" not in path.parts
        and "__pycache__" not in path.parts
    ]

    if not python_files:
        return fail("No Python files found.")

    return run([sys.executable, "-m", "py_compile", *python_files])


def project_has_source_markdown(project_dir: Path) -> bool:
    return any(
        path.is_file()
        and path.suffix.lower() == ".md"
        and not any(
            part in IGNORED_SOURCE_DIR_NAMES
            for part in path.relative_to(project_dir).parts
        )
        for path in project_dir.rglob("*.md")
    )


def ignored_project_candidate(path: Path) -> bool:
    try:
        relative = path.relative_to(OUTPUT_ROOT)
    except ValueError:
        return True

    return any(part in IGNORED_SOURCE_DIR_NAMES for part in relative.parts)


def discover_projects() -> list[Path]:
    if not OUTPUT_ROOT.is_dir():
        return []

    candidates = [
        path
        for path in OUTPUT_ROOT.rglob("*")
        if path.is_dir()
        and not ignored_project_candidate(path)
        and project_has_source_markdown(path)
    ]

    leaf_projects = []

    for candidate in candidates:
        has_child_project = any(
            other != candidate and candidate in other.parents for other in candidates
        )

        if not has_child_project:
            leaf_projects.append(candidate)

    return sorted(leaf_projects)


def check_project_state_files() -> int:
    projects = discover_projects()

    if not projects:
        return fail("No output projects found.")

    checked = 0

    for project_dir in projects:
        if not project_has_source_markdown(project_dir):
            continue

        checked += 1

        required_state = [
            project_dir / ".state" / "flatten.db",
            project_dir / ".state" / "incremental.db",
            project_dir / ".state" / "merge.db",
        ]

        for db_path in required_state:
            if not db_path.is_file():
                print(f"[MISSING STATE] {db_path}")
                return fail("A project is missing pipeline state database.")

        merged_current = project_dir / "_merged" / "current"

        if not merged_current.is_dir():
            print(f"[MISSING MERGED CURRENT] {merged_current}")
            return fail("A project is missing _merged/current output.")

    if checked == 0:
        return fail("No source markdown projects found.")

    print(f"[OK] Project state files verified: {checked}")
    return 0


def check_markdown_readonly() -> int:
    writable: list[Path] = []

    for project_dir in discover_projects():
        for md_file in project_dir.rglob("*.md"):
            mode = stat.S_IMODE(md_file.stat().st_mode)

            if mode != READ_ONLY_MODE:
                writable.append(md_file)

    if writable:
        for path in writable[:50]:
            print(f"[NOT READONLY] {path}")

        if len(writable) > 50:
            print(f"[NOT READONLY] ... and {len(writable) - 50} more")

        return fail("Some Markdown files are not locked as read-only.")

    print("[OK] Markdown files are read-only.")
    return 0


def main() -> int:
    print()
    print("DOCSYNC RELEASE VALIDATION")
    print("==========================")

    checks = [
        check_required_files,
        check_forbidden_paths,
        check_pycache_absent,
        compile_python,
        check_project_state_files,
        check_markdown_readonly,
    ]

    for check in checks:
        code = check()
        if code != 0:
            print()
            print("RELEASE VALIDATION FAILED")
            return code

    print()
    print("RELEASE VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
