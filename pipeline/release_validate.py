#!/usr/bin/env python3
"""Validate DOCSYNC source code and generated source projects."""

from __future__ import annotations

import stat
from collections.abc import Callable
from pathlib import Path

from pipeline.constants import READ_ONLY_MODE
from pipeline.paths import (
    PROJECT_ROOT,
    discover_project_directories,
)

REQUIRED_FILES = (
    PROJECT_ROOT / "crawler" / "crawler_engine.py",
    PROJECT_ROOT / "crawler" / "markdown_writer.py",
    PROJECT_ROOT / "pipeline" / "run_pipeline.py",
    PROJECT_ROOT / "pipeline" / "docs_pipeline_runner.py",
    PROJECT_ROOT / "pipeline" / "flatten_docs.py",
    PROJECT_ROOT / "pipeline" / "incremental_update.py",
    PROJECT_ROOT / "pipeline" / "merge_engine.py",
)

FORBIDDEN_PATHS = (PROJECT_ROOT / "pipeline" / "incremental_state.db",)

CODE_ROOTS = (
    PROJECT_ROOT / "crawler",
    PROJECT_ROOT / "pipeline",
    PROJECT_ROOT / "tests",
    PROJECT_ROOT / "tools",
)

MERGED_DIRECTORY_NAME = "_merged"

ValidationCheck = Callable[[], int]


def fail(message: str) -> int:
    """Print a validation failure and return a non-zero status."""

    print(f"[FAIL] {message}")
    return 1


def check_required_files() -> int:
    """Verify that all release-critical source files exist."""

    missing_files = [
        required_file for required_file in REQUIRED_FILES if not required_file.is_file()
    ]

    if missing_files:
        for missing_file in missing_files:
            print(f"[MISSING] {missing_file}")

        return fail("Required release files are missing.")

    print("[OK] Required files exist.")
    return 0


def check_forbidden_paths() -> int:
    """Verify that forbidden legacy pipeline paths are absent."""

    existing_paths = [
        forbidden_path for forbidden_path in FORBIDDEN_PATHS if forbidden_path.exists()
    ]

    if existing_paths:
        for existing_path in existing_paths:
            print(f"[FORBIDDEN] {existing_path}")

        return fail("Forbidden legacy pipeline paths still exist.")

    print("[OK] Forbidden legacy pipeline paths are absent.")
    return 0


def discover_project_python_files() -> tuple[Path, ...]:
    """Return all project Python files that must pass syntax validation."""

    python_files = {
        python_file
        for code_root in CODE_ROOTS
        if code_root.is_dir()
        for python_file in code_root.rglob("*.py")
        if python_file.is_file()
    }

    crawler_cli = PROJECT_ROOT / "crawler_cli.py"
    if crawler_cli.is_file():
        python_files.add(crawler_cli)

    return tuple(sorted(python_files))


def validate_python_syntax(python_file: Path) -> str | None:
    """Return a syntax error description without writing bytecode files."""

    try:
        source = python_file.read_text(encoding="utf-8")
        _ = compile(source, str(python_file), "exec")
    except (OSError, UnicodeError, SyntaxError) as error:
        return str(error)

    return None


def check_project_python_syntax() -> int:
    """Validate project Python syntax without modifying the filesystem."""

    python_files = discover_project_python_files()

    if not python_files:
        return fail("No project Python files found.")

    invalid_files = [
        (python_file, error_message)
        for python_file in python_files
        if (error_message := validate_python_syntax(python_file)) is not None
    ]

    if invalid_files:
        for python_file, error_message in invalid_files:
            print(f"[INVALID PYTHON] {python_file}: {error_message}")

        return fail("One or more project Python files failed syntax validation.")

    print(f"[OK] Python syntax verified: {len(python_files)}")
    return 0


def discover_source_markdown_files(
    project_directory: Path,
) -> tuple[Path, ...]:
    """Return source Markdown files excluding generated merge outputs."""

    merged_directory = project_directory / MERGED_DIRECTORY_NAME

    return tuple(
        sorted(
            markdown_file
            for markdown_file in project_directory.rglob("*.md")
            if markdown_file.is_file() and merged_directory not in markdown_file.parents
        )
    )


def contains_source_markdown_files(project_directory: Path) -> bool:
    """Return whether a source project contains source Markdown files."""

    return bool(discover_source_markdown_files(project_directory))


def discover_markdown_projects() -> tuple[Path, ...]:
    """Return discovered projects containing source Markdown files."""

    return tuple(
        project_directory
        for project_directory in discover_project_directories()
        if contains_source_markdown_files(project_directory)
    )


def check_source_projects() -> int:
    """Verify that dynamically discovered Markdown source projects exist."""

    project_directories = discover_markdown_projects()

    if not project_directories:
        message = (
            "No dynamically discovered source projects containing "
            "Markdown files were found."
        )
        return fail(message)

    print(f"[OK] Markdown source projects discovered: {len(project_directories)}")
    return 0


def discover_writable_markdown_files() -> tuple[Path, ...]:
    """Return source Markdown files that are not strictly read-only."""

    return tuple(
        markdown_file
        for project_directory in discover_markdown_projects()
        for markdown_file in discover_source_markdown_files(project_directory)
        if stat.S_IMODE(markdown_file.stat().st_mode) != READ_ONLY_MODE
    )


def check_markdown_readonly() -> int:
    """Verify that source Markdown files are strictly read-only."""

    writable_files = discover_writable_markdown_files()

    if writable_files:
        displayed_files = writable_files[:50]

        for writable_file in displayed_files:
            print(f"[NOT READONLY] {writable_file}")

        remaining_count = len(writable_files) - len(displayed_files)
        if remaining_count > 0:
            print(f"[NOT READONLY] ... and {remaining_count} more")

        return fail("Some source Markdown files are not read-only.")

    print("[OK] Source Markdown files are read-only.")
    return 0


def release_checks() -> tuple[ValidationCheck, ...]:
    """Return release validation checks in execution order."""

    return (
        check_required_files,
        check_forbidden_paths,
        check_project_python_syntax,
        check_source_projects,
        check_markdown_readonly,
    )


def main() -> int:
    """Run all release validation checks without modifying project files."""

    print()
    print("DOCSYNC RELEASE VALIDATION")
    print("==========================")

    for validation_check in release_checks():
        if validation_check() != 0:
            print()
            print("RELEASE VALIDATION FAILED")
            return 1

    print()
    print("RELEASE VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
