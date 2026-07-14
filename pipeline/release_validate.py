#!/usr/bin/env python3
"""Validate DOCSYNC source code and generated project outputs."""

from __future__ import annotations

import stat
from collections.abc import Callable
from pathlib import Path

from pipeline.paths import (
    PROJECT_ROOT,
    discover_project_output_directories,
)

READ_ONLY_MODE = 0o444

REQUIRED_FILES = (
    PROJECT_ROOT / "crawler" / "crawler_engine.py",
    PROJECT_ROOT / "crawler" / "markdown_writer.py",
    PROJECT_ROOT / "pipeline" / "run_pipeline.py",
    PROJECT_ROOT / "pipeline" / "docs_pipeline_runner.py",
    PROJECT_ROOT / "pipeline" / "flatten_docs.py",
    PROJECT_ROOT / "pipeline" / "incremental_update.py",
    PROJECT_ROOT / "pipeline" / "merge_engine.py",
)

FORBIDDEN_PATHS = (
    PROJECT_ROOT / "pipeline" / "incremental_state.db",
)

CODE_ROOTS = (
    PROJECT_ROOT / "crawler",
    PROJECT_ROOT / "pipeline",
    PROJECT_ROOT / "tests",
    PROJECT_ROOT / "tools",
)

ValidationCheck = Callable[[], int]


def fail(message: str) -> int:
    """Print a validation failure and return a non-zero status."""
    print(f"[FAIL] {message}")
    return 1


def check_required_files() -> int:
    """Verify that all release-critical source files exist."""
    missing_files = [
        required_file
        for required_file in REQUIRED_FILES
        if not required_file.is_file()
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
        forbidden_path
        for forbidden_path in FORBIDDEN_PATHS
        if forbidden_path.exists()
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
        compile(source, str(python_file), "exec")
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
        if (
            error_message := validate_python_syntax(python_file)
        )
        is not None
    ]

    if invalid_files:
        for python_file, error_message in invalid_files:
            print(f"[INVALID PYTHON] {python_file}: {error_message}")

        return fail("One or more project Python files failed syntax validation.")

    print(f"[OK] Python syntax verified: {len(python_files)}")
    return 0


def contains_markdown_files(output_directory: Path) -> bool:
    """Return whether an output directory contains Markdown files."""
    return any(
        markdown_file.is_file()
        for markdown_file in output_directory.rglob("*.md")
    )


def discover_markdown_output_directories() -> tuple[Path, ...]:
    """Return discovered crawler outputs containing Markdown files."""
    return tuple(
        output_directory
        for output_directory in discover_project_output_directories()
        if output_directory.is_dir()
        and contains_markdown_files(output_directory)
    )


def required_state_paths(output_directory: Path) -> tuple[Path, Path]:
    """Return required pipeline state databases for one output directory."""
    state_directory = output_directory / ".state"

    return (
        state_directory / "flatten.db",
        state_directory / "incremental.db",
    )


def discover_missing_state_paths(
    output_directory: Path,
) -> tuple[Path, ...]:
    """Return missing state databases for one crawler output directory."""
    return tuple(
        state_path
        for state_path in required_state_paths(output_directory)
        if not state_path.is_file()
    )


def check_output_state(output_directory: Path) -> int:
    """Verify required state databases for one crawler output directory."""
    missing_state_paths = discover_missing_state_paths(output_directory)

    if missing_state_paths:
        for missing_state_path in missing_state_paths:
            print(f"[MISSING STATE] {missing_state_path}")

        return fail(
            f"Pipeline state is incomplete for: {output_directory}"
        )

    return 0


def check_project_outputs() -> int:
    """Verify pipeline state for every discovered crawler output."""
    output_directories = discover_markdown_output_directories()

    if not output_directories:
        return fail(
            "No dynamically discovered output directories containing "
            "Markdown files were found."
        )

    for output_directory in output_directories:
        if check_output_state(output_directory) != 0:
            return 1

    print(f"[OK] Project state verified: {len(output_directories)}")
    return 0


def discover_writable_markdown_files() -> tuple[Path, ...]:
    """Return crawler output Markdown files that are not read-only."""
    return tuple(
        markdown_file
        for output_directory in discover_markdown_output_directories()
        for markdown_file in output_directory.rglob("*.md")
        if markdown_file.is_file()
        and stat.S_IMODE(markdown_file.stat().st_mode) != READ_ONLY_MODE
    )


def check_markdown_readonly() -> int:
    """Verify that crawler output Markdown files are strictly read-only."""
    writable_files = discover_writable_markdown_files()

    if writable_files:
        displayed_files = writable_files[:50]

        for writable_file in displayed_files:
            print(f"[NOT READONLY] {writable_file}")

        remaining_count = len(writable_files) - len(displayed_files)
        if remaining_count > 0:
            print(f"[NOT READONLY] ... and {remaining_count} more")

        return fail("Some crawler Markdown files are not read-only.")

    print("[OK] Crawler Markdown files are read-only.")
    return 0


def release_checks() -> tuple[ValidationCheck, ...]:
    """Return release validation checks in execution order."""
    return (
        check_required_files,
        check_forbidden_paths,
        check_project_python_syntax,
        check_project_outputs,
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
