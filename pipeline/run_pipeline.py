#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from pipeline.paths import DOCS_PIPELINE_RUNNER, OUTPUT_ROOT, PROJECT_ROOT
from pipeline.subprocess_runner import run_python_script

IGNORED_SOURCE_DIR_NAMES = {
    "_merged",
    "_archive",
    "_raw",
    ".state",
    ".git",
    "__pycache__",
}


def project_has_markdown(project_dir: Path) -> bool:
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
    if not OUTPUT_ROOT.exists():
        return []

    candidates = [
        path
        for path in OUTPUT_ROOT.rglob("*")
        if path.is_dir()
        and not ignored_project_candidate(path)
        and project_has_markdown(path)
    ]

    leaf_projects = []

    for candidate in candidates:
        has_child_project = any(
            other != candidate and candidate in other.parents for other in candidates
        )

        if not has_child_project:
            leaf_projects.append(candidate)

    return sorted(leaf_projects)


def run_project(project_dir: Path) -> int:
    print()
    print("=" * 70)
    print(f"PROJECT: {project_dir.name}")
    print("=" * 70)

    return run_python_script(
        script=DOCS_PIPELINE_RUNNER,
        args=(str(project_dir),),
        cwd=PROJECT_ROOT,
    )


def main() -> int:
    print()
    print("DOCSYNC RELEASE PIPELINE")
    print("========================")

    if not DOCS_PIPELINE_RUNNER.is_file():
        print(f"[ERROR] Missing runner: {DOCS_PIPELINE_RUNNER}")
        return 1

    projects = discover_projects()

    if not projects:
        print(f"[ERROR] No project folders found under: {OUTPUT_ROOT}")
        return 1

    processed = 0
    skipped = 0
    failed = 0

    for project_dir in projects:
        if not project_has_markdown(project_dir):
            print(f"[SKIP] No source markdown files: {project_dir}")
            skipped += 1
            continue

        code = run_project(project_dir)

        if code == 0:
            processed += 1
        else:
            failed += 1
            print(f"[FAILED] {project_dir.name}")

    print()
    print("=" * 70)
    print("DOCSYNC RELEASE PIPELINE SUMMARY")
    print("--------------------------------")
    print(f"Projects found: {len(projects)}")
    print(f"Processed: {processed}")
    print(f"Skipped: {skipped}")
    print(f"Failed: {failed}")

    if failed:
        return 1

    print("PIPELINE COMPLETE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
