#!/usr/bin/env python3

from __future__ import annotations

import ast
import json
import py_compile
import shutil
import stat
import subprocess  # nosec B404 - subprocess module is required for controlled local tooling
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = PROJECT_ROOT / "logs" / "project_audit"

IGNORED_TREE_PARTS = {
    ".git",
    ".venv",
    "backups",
    "logs",
    "output",
    "storage",
}

REMOVE_DIRECTORIES = {
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "htmlcov",
}

REMOVE_FILE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".tmp",
    ".swp",
    ".swo",
    ".bak",
}

SCRIPT_SUFFIXES = {
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
}

EXPECTED_ROOT_FILES = {
    ".gitignore",
    "README.md",
    "TODO.md",
    "src/docsync/crawler.py",
    "main.py",
    "pyproject.toml",
    "uv.lock",
}

ALLOWED_ROOT_DIRECTORIES = {
    ".git",
    ".venv",
    "backups",
    "data",
    "logs",
    "metrics",
    "output",
    "src",
    "storage",
    "tests",
    "tools",
}

ALLOWED_EXECUTABLE_PYTHON_FILES = {
    "main.py",
}


@dataclass
class AuditReport:
    started_at: str
    finished_at: str | None = None
    project_root: str = str(PROJECT_ROOT)
    python_files: list[str] = field(default_factory=list)
    compiled_python_files: list[str] = field(default_factory=list)
    shell_files_found: list[str] = field(default_factory=list)
    shell_files_removed: list[str] = field(default_factory=list)
    obsolete_launchers_removed: list[str] = field(default_factory=list)
    cache_directories_removed: list[str] = field(default_factory=list)
    temporary_files_removed: list[str] = field(default_factory=list)
    executable_non_python_files: list[str] = field(default_factory=list)
    imported_modules: list[str] = field(default_factory=list)
    dependency_check: dict[str, object] = field(default_factory=dict)
    security_markers: dict[str, bool] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)
    status: str = "running"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def relative(path: Path) -> str:
    return str(path.relative_to(PROJECT_ROOT))


def run(
    command: list[str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 - argument list is constructed internally without shell execution
        command,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def ignored(path: Path) -> bool:
    try:
        relative_parts = path.relative_to(PROJECT_ROOT).parts
    except ValueError:
        return True

    return any(part in IGNORED_TREE_PARTS for part in relative_parts)


def iter_project_files() -> Iterable[Path]:
    for path in PROJECT_ROOT.rglob("*"):
        if ignored(path):
            continue

        if path.is_file():
            yield path


def remove_shell_files(
    report: AuditReport,
) -> None:
    for path in sorted(iter_project_files()):
        if path.suffix.lower() not in SCRIPT_SUFFIXES:
            continue

        name = relative(path)
        report.shell_files_found.append(name)
        path.unlink()
        report.shell_files_removed.append(name)


def remove_obsolete_launchers(
    report: AuditReport,
) -> None:
    launcher = PROJECT_ROOT / "docsync"

    if not launcher.exists() or not launcher.is_file():
        return

    content = launcher.read_text(
        encoding="utf-8",
        errors="replace",
    )

    first_line = content.splitlines()[0] if content.splitlines() else ""

    looks_like_launcher = (
        first_line.startswith("#!")
        or "uv run" in content
        or "python main.py" in content
        or "src/docsync/crawler.py" in content
    )

    if looks_like_launcher:
        launcher.unlink()
        report.obsolete_launchers_removed.append("docsync")
    else:
        report.issues.append(
            "Root file 'docsync' is not recognized as a "
            "launcher and was not deleted automatically."
        )


def remove_cache_directories(
    report: AuditReport,
) -> None:
    directories = sorted(
        (
            path
            for path in PROJECT_ROOT.rglob("*")
            if path.is_dir() and path.name in REMOVE_DIRECTORIES and not ignored(path)
        ),
        key=lambda item: len(item.parts),
        reverse=True,
    )

    for directory in directories:
        if not directory.exists():
            continue

        name = relative(directory)
        shutil.rmtree(directory)
        report.cache_directories_removed.append(name)


def remove_temporary_files(
    report: AuditReport,
) -> None:
    for path in sorted(iter_project_files()):
        if path.suffix.lower() not in REMOVE_FILE_SUFFIXES:
            continue

        name = relative(path)
        path.unlink()
        report.temporary_files_removed.append(name)


def validate_python(
    report: AuditReport,
) -> None:
    python_files = sorted(path for path in iter_project_files() if path.suffix == ".py")

    if not python_files:
        report.issues.append("No Python files were found.")
        return

    compile_root = PROJECT_ROOT / ".audit_compile_cache"

    if compile_root.exists():
        shutil.rmtree(compile_root)

    compile_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        for index, path in enumerate(
            python_files,
            start=1,
        ):
            name = relative(path)
            report.python_files.append(name)

            cache_file = compile_root / f"{index:04d}.pyc"

            try:
                py_compile.compile(
                    str(path),
                    cfile=str(cache_file),
                    doraise=True,
                )
            except py_compile.PyCompileError as error:
                report.issues.append(f"Python compilation failed for {name}: {error}")
            else:
                report.compiled_python_files.append(name)
    finally:
        shutil.rmtree(
            compile_root,
            ignore_errors=True,
        )


def collect_imports(
    report: AuditReport,
) -> None:
    modules: set[str] = set()

    for filename in report.python_files:
        path = PROJECT_ROOT / filename

        try:
            tree = ast.parse(
                path.read_text(encoding="utf-8"),
                filename=filename,
            )
        except Exception as error:
            report.issues.append(f"Could not parse imports in {filename}: {error}")
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    modules.add(alias.name.split(".", 1)[0])

            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".", 1)[0])

    report.imported_modules = sorted(modules)


def inspect_executable_files(
    report: AuditReport,
) -> None:
    for path in sorted(iter_project_files()):
        mode = path.stat().st_mode

        if not mode & stat.S_IXUSR:
            continue

        if path.suffix == ".py" and path.name in ALLOWED_EXECUTABLE_PYTHON_FILES:
            continue

        report.executable_non_python_files.append(relative(path))

    for name in report.executable_non_python_files:
        report.issues.append(f"Executable non-entry file requires review: {name}")


def ensure_project_files(
    report: AuditReport,
) -> None:
    required = {
        "main.py",
        "src/docsync/crawler.py",
        "pyproject.toml",
    }

    for filename in sorted(required):
        if not (PROJECT_ROOT / filename).is_file():
            report.issues.append(f"Required project file is missing: {filename}")

    readme = PROJECT_ROOT / "README.md"

    if not readme.exists():
        readme.write_text(
            "# docsync\n\n"
            "Safe, incremental documentation crawler "
            "built with Crawlee for Python.\n\n"
            "## Run\n\n"
            "```bash\n"
            "uv run python main.py "
            "https://example.com/docs\n"
            "```\n",
            encoding="utf-8",
        )

    gitignore = PROJECT_ROOT / ".gitignore"

    required_lines = {
        ".audit_compile_cache/",
        ".mypy_cache/",
        ".pytest_cache/",
        ".ruff_cache/",
        ".venv/",
        "__pycache__/",
        "*.py[cod]",
        "backups/",
        "logs/",
        "output/",
        "storage/",
    }

    existing_lines: set[str] = set()

    if gitignore.exists():
        existing_lines = {
            line.strip()
            for line in gitignore.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }

    gitignore.write_text(
        "\n".join(sorted(existing_lines | required_lines)) + "\n",
        encoding="utf-8",
    )


def check_dependencies(
    report: AuditReport,
) -> None:
    result = run(
        [
            "uv",
            "sync",
            "--frozen",
        ]
    )

    report.dependency_check = {
        "return_code": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
    }

    if result.returncode != 0:
        report.issues.append(
            "uv sync --frozen failed. See dependency_check in the audit report."
        )


def inspect_security_markers(
    report: AuditReport,
) -> None:
    source = ""

    for filename in (
        "main.py",
        "src/docsync/crawler.py",
    ):
        path = PROJECT_ROOT / filename

        if path.exists():
            source += (
                "\n"
                + path.read_text(
                    encoding="utf-8",
                    errors="replace",
                ).lower()
            )

    markers = {
        "robots_txt": ("robots.txt" in source or "robotfileparser" in source),
        "crawl_delay": ("crawl-delay" in source or "crawl_delay" in source),
        "single_concurrency": (
            "max_concurrency=1" in source
            or "max_concurrency = 1" in source
            or "concurrency: 1" in source
        ),
        "rate_limit": (
            "request(s)/minute" in source
            or "requests_per_minute" in source
            or "max_requests_per_minute" in source
            or "request_rate" in source
        ),
        "ssrf_protection": (
            "is_private" in source
            and "is_loopback" in source
            and "getaddrinfo" in source
        ),
        "test_mode_is_explicit": ("docsync_test_mode" in source and '== "1"' in source),
        "duplicate_detection": ("duplicate" in source and "content_hash" in source),
        "incremental_sync": ("incremental" in source and "refresh_hours" in source),
        "retry_protection": (
            "max_request_retries=0" in source
            or "max_request_retries = 0" in source
            or "retries: disabled" in source
        ),
        "session_rotation_disabled": (
            "session rotation: disabled" in source
            or "use_session_pool=false" in source
            or "use_session_pool = false" in source
        ),
        "markdown_output": (".md" in source and "markdown" in source),
        "per_run_logs": ("logs_root" in source and "run_directory" in source),
    }

    report.security_markers = markers

    for marker, found in markers.items():
        if not found:
            report.issues.append(f"Security or behavior marker not detected: {marker}")


def check_root_structure(
    report: AuditReport,
) -> None:
    for path in sorted(PROJECT_ROOT.iterdir()):
        if path.name == "__pycache__":
            continue

        if path.is_dir():
            if path.name not in ALLOWED_ROOT_DIRECTORIES:
                report.issues.append(f"Unexpected root directory: {path.name}")
            continue

        if path.name in EXPECTED_ROOT_FILES:
            continue

        if path.suffix == ".py":
            continue

        if path.name.startswith("."):
            continue

        report.issues.append(f"Review unexpected root file: {path.name}")


def write_report(
    report: AuditReport,
) -> Path:
    REPORTS_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")

    report_path = REPORTS_ROOT / (f"audit_{timestamp}.json")

    report_path.write_text(
        json.dumps(
            asdict(report),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    (REPORTS_ROOT / "LATEST").write_text(
        str(report_path.resolve()) + "\n",
        encoding="utf-8",
    )

    return report_path


def main() -> int:
    report = AuditReport(
        started_at=utc_now(),
    )

    ensure_project_files(report)
    remove_shell_files(report)
    remove_obsolete_launchers(report)
    remove_cache_directories(report)
    remove_temporary_files(report)
    validate_python(report)
    collect_imports(report)
    inspect_executable_files(report)
    check_dependencies(report)
    inspect_security_markers(report)
    check_root_structure(report)

    report.finished_at = utc_now()
    report.status = "passed" if not report.issues else "completed_with_findings"

    report_path = write_report(report)

    print("DOCSYNC PROJECT AUDIT")
    print("=====================")
    print(f"Status: {report.status}")
    print(f"Python files: {len(report.python_files)}")
    print(f"Compiled Python files: {len(report.compiled_python_files)}")
    print(f"Removed shell files: {len(report.shell_files_removed)}")
    print(f"Removed obsolete launchers: {len(report.obsolete_launchers_removed)}")
    print(f"Removed cache directories: {len(report.cache_directories_removed)}")
    print(f"Removed temporary files: {len(report.temporary_files_removed)}")
    print(f"Findings: {len(report.issues)}")
    print(f"Report: {report_path}")

    if report.issues:
        print()
        print("Findings:")

        for issue in report.issues:
            print(f"- {issue}")

    return 0 if not report.issues else 2


if __name__ == "__main__":
    raise SystemExit(main())

IGNORED_MIGRATION_DIRECTORY = ".docsync-migration"
