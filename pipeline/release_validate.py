#!/usr/bin/env python3
"""Validate DOCSYNC source code and generated project outputs."""

from __future__ import annotations

import stat
from pathlib import Path

from pipeline.paths import (
    OUTPUT_DIR_NAME,
    PROJECT_ROOT,
    discover_project_output_directories,
)
from pipeline.subprocess_runner import run_command

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


def fail(message: str) -> int:
    """Print a validation failure and return a non-zero status."""
    print(f"[FAIL] {message}")
    return 1


def check_required_files() -> int:
    """Verify that all release-critical source files exist."""
    missing = [path for path in REQUIRED_FILES if not path.is_file()]

    if missing:
        for path in missing:
            print(f"[MISSING] {path}")
        return fail("Required release files are missing.")

    print("[OK] Required files exist.")
    return 0


def check_forbidden_paths() -> int:
    """Verify that forbidden legacy pipeline paths are absent."""
    existing = [path for path in FORBIDDEN_PATHS if path.exists()]

    if existing:
        for path in existing:
            print(f"[FORBIDDEN] {path}")
        return fail("Forbidden legacy pipeline paths still exist.")

    print("[OK] Forbidden legacy pipeline paths are absent.")
    return 0


def clean_project_pycache() -> int:
    """Remove project-local Python bytecode cache directories."""
    cache_dirs = {
        cache
        for root in CODE_ROOTS
        if root.is_dir()
        for cache in root.rglob("__pycache__")
        if cache.is_dir()
    }

    root_cache = PROJECT_ROOT / "__pycache__"
    if root_cache.is_dir():
        cache_dirs.add(root_cache)

    for cache_dir in sorted(cache_dirs, reverse=True):
        for item in cache_dir.iterdir():
            if item.is_file() or item.is_symlink():
                item.unlink()

        try:
            cache_dir.rmdir()
        except OSError:
            return fail(f"Could not remove __pycache__: {cache_dir}")

        print(f"[CLEANED PYCACHE] {cache_dir}")

    print("[OK] Project __pycache__ directories cleaned.")
    return 0


def project_python_files() -> list[Path]:
    """Return all project Python files that must compile."""
    files = {
        path
        for root in CODE_ROOTS
        if root.is_dir()
        for path in root.rglob("*.py")
        if path.is_file()
    }

    cli_path = PROJECT_ROOT / "crawler_cli.py"
    if cli_path.is_file():
        files.add(cli_path)

    return sorted(files)


def compile_project_python() -> int:
    """Compile all project Python files through uv."""
    files = project_python_files()

    if not files:
        return fail("No project Python files found.")

    command = [
        "uv",
        "run",
        "python",
        "-m",
        "py_compile",
        *(str(path.relative_to(PROJECT_ROOT)) for path in files),
    ]
    return run_command(command, cwd=PROJECT_ROOT)


def discover_project_directories() -> list[Path]:
    """Return project directories owning discovered crawler outputs."""
    output_directories = discover_project_output_directories(
        require_markdown=True
    )
    return sorted({output_dir.parent for output_dir in output_directories})


def check_project_outputs() -> int:
    """Verify pipeline state for every discovered crawler project."""
    project_directories = discover_project_directories()

    if not project_directories:
        return fail(
            "No sources/<project>/output directories containing Markdown "
            "were found."
        )

    for project_dir in project_directories:
        output_dir = project_dir / OUTPUT_DIR_NAME

        if not output_dir.is_dir():
            print(f"[MISSING OUTPUT] {output_dir}")
            return fail("A discovered project is missing its crawler output.")

        required_paths = (
            project_dir / ".state" / "flatten.db",
            project_dir / ".state" / "incremental.db",
        )

        for path in required_paths:
            if not path.is_file():
                print(f"[MISSING STATE] {path}")
                return fail("A project is missing required pipeline state.")

    print(f"[OK] Project state verified: {len(project_directories)}")
    return 0


def check_markdown_readonly() -> int:
    """Verify that crawler output Markdown files are read-only."""
    writable = [
        path
        for output_dir in discover_project_output_directories(
            require_markdown=True
        )
        for path in output_dir.rglob("*.md")
        if path.is_file()
        and stat.S_IMODE(path.stat().st_mode) != READ_ONLY_MODE
    ]

    if writable:
        for path in writable[:50]:
            print(f"[NOT READONLY] {path}")

        if len(writable) > 50:
            print(f"[NOT READONLY] ... and {len(writable) - 50} more")

        return fail("Some crawler Markdown files are not read-only.")

    print("[OK] Crawler Markdown files are read-only.")
    return 0


def main() -> int:
    """Run all release validation checks."""
    print()
    print("DOCSYNC RELEASE VALIDATION")
    print("==========================")

    checks = (
        check_required_files,
        check_forbidden_paths,
        clean_project_pycache,
        compile_project_python,
        check_project_outputs,
        check_markdown_readonly,
    )

    for check in checks:
        if check() != 0:
            print()
            print("RELEASE VALIDATION FAILED")
            return 1

    print()
    print("RELEASE VALIDATION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
