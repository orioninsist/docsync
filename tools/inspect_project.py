from __future__ import annotations

import ast
import json
import os
import platform
import re
import shutil
import subprocess  # nosec B404 - subprocess module is required for controlled local tooling
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError as exc:
    raise SystemExit("Python 3.11 or newer is required.") from exc


PROJECT_ROOT = Path("/mnt/local/areas/docsync").resolve()
REPORT_DIR = PROJECT_ROOT / "logs" / "project_audit"
REPORT_PATH = REPORT_DIR / "initial_audit.md"
JSON_REPORT_PATH = REPORT_DIR / "initial_audit.json"

IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    ".vscode",
    "__pycache__",
    "node_modules",
}

GENERATED_DIRECTORY_NAMES = {
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "htmlcov",
}

TEMPORARY_FILE_PATTERNS = (
    re.compile(r".*~$"),
    re.compile(r".*\.bak$", re.IGNORECASE),
    re.compile(r".*\.orig$", re.IGNORECASE),
    re.compile(r".*\.rej$", re.IGNORECASE),
    re.compile(r".*\.swp$", re.IGNORECASE),
    re.compile(r".*\.tmp$", re.IGNORECASE),
    re.compile(r"^\.\#.*"),
)

SHELL_SUFFIXES = {".sh", ".bash", ".zsh", ".fish"}

LIKELY_SOURCE_DIRECTORIES = {
    "src",
    "docsync",
    "app",
    "lib",
    "scripts",
    "tools",
    "tests",
}

LIKELY_RUNTIME_DIRECTORIES = {
    "data",
    "storage",
    "output",
    "outputs",
    "logs",
    "metrics",
    "checkpoints",
}

EXPECTED_ROOT_FILES = {
    ".gitignore",
    ".python-version",
    "LICENSE",
    "README.md",
    "TODO.md",
    "main.py",
    "pyproject.toml",
    "uv.lock",
}

RECOMMENDED_DEV_TOOLS = {
    "pytest": "Testing",
    "pytest-cov": "Coverage reporting",
    "ruff": "Linting and formatting",
    "mypy": "Static type checking",
}

OPTIONAL_DEV_TOOLS = {
    "pre-commit": "Local quality gates",
    "pip-audit": "Dependency vulnerability auditing",
    "radon": "Complexity analysis",
}

NETWORK_SAFETY_TERMS = {
    "robots": (
        "robots.txt",
        "robotfileparser",
        "robots",
    ),
    "throttling": (
        "sleep(",
        "delay",
        "throttle",
        "rate_limit",
        "rate-limit",
        "max_requests_per_minute",
        "max_requests_per_crawl",
    ),
    "concurrency": (
        "max_concurrency",
        "min_concurrency",
        "concurrency",
        "autoscaled_pool",
    ),
    "retry_control": (
        "max_request_retries",
        "retry",
        "backoff",
    ),
    "session_control": (
        "use_session_pool",
        "session_pool",
        "session_rotation",
    ),
    "duplicate_control": (
        "content_hash",
        "checksum",
        "sha256",
        "duplicate",
        "dedup",
        "unique_key",
        "canonical",
    ),
    "incremental_sync": (
        "incremental",
        "last_modified",
        "etag",
        "content_hash",
        "checkpoint",
    ),
    "multi_process_safety": (
        "filelock",
        "fcntl",
        "portalocker",
        "sqlite",
        "transaction",
        "atomic",
        "lock",
    ),
}


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    return_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class PythonFileInfo:
    path: str
    lines: int
    classes: int
    functions: int
    async_functions: int
    imports: tuple[str, ...]
    syntax_ok: bool
    syntax_error: str | None


def run_command(command: Iterable[str], cwd: Path = PROJECT_ROOT) -> CommandResult:
    command_tuple = tuple(command)

    try:
        completed = subprocess.run(  # nosec B603 - argument list is constructed internally without shell execution
            command_tuple,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        return CommandResult(
            command=command_tuple,
            return_code=127,
            stdout="",
            stderr=f"Executable not found: {command_tuple[0]}",
        )
    except subprocess.TimeoutExpired:
        return CommandResult(
            command=command_tuple,
            return_code=124,
            stdout="",
            stderr="Command timed out after 120 seconds.",
        )

    return CommandResult(
        command=command_tuple,
        return_code=completed.returncode,
        stdout=completed.stdout.strip(),
        stderr=completed.stderr.strip(),
    )


def relative(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT).as_posix()


def should_ignore_directory(path: Path) -> bool:
    return any(part in IGNORED_DIRECTORY_NAMES for part in path.parts)


def iter_project_files() -> Iterable[Path]:
    for path in sorted(PROJECT_ROOT.rglob("*")):
        if not path.is_file():
            continue

        relative_path = path.relative_to(PROJECT_ROOT)

        if should_ignore_directory(relative_path):
            continue

        yield path


def iter_project_directories() -> Iterable[Path]:
    for path in sorted(PROJECT_ROOT.rglob("*")):
        if not path.is_dir():
            continue

        relative_path = path.relative_to(PROJECT_ROOT)

        if should_ignore_directory(relative_path):
            continue

        yield path


def read_text_safely(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def load_pyproject() -> tuple[dict[str, Any], str | None]:
    pyproject_path = PROJECT_ROOT / "pyproject.toml"

    if not pyproject_path.is_file():
        return {}, "pyproject.toml does not exist."

    try:
        with pyproject_path.open("rb") as file:
            return tomllib.load(file), None
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return {}, str(exc)


def normalize_dependency_name(requirement: str) -> str:
    name = re.split(r"[<>=!~\[\s;]", requirement, maxsplit=1)[0]
    return name.strip().lower().replace("_", "-")


def extract_dependencies(pyproject: dict[str, Any]) -> dict[str, list[str]]:
    project = pyproject.get("project", {})
    dependency_groups = pyproject.get("dependency-groups", {})
    tool = pyproject.get("tool", {})
    poetry = tool.get("poetry", {})

    runtime_dependencies: list[str] = []
    development_dependencies: list[str] = []

    for dependency in project.get("dependencies", []):
        if isinstance(dependency, str):
            runtime_dependencies.append(dependency)

    optional_dependencies = project.get("optional-dependencies", {})
    for group_name, dependencies in optional_dependencies.items():
        if not isinstance(dependencies, list):
            continue

        destination = (
            development_dependencies
            if group_name.lower() in {"dev", "test", "lint", "quality"}
            else runtime_dependencies
        )

        destination.extend(
            dependency for dependency in dependencies if isinstance(dependency, str)
        )

    for group_name, dependencies in dependency_groups.items():
        if not isinstance(dependencies, list):
            continue

        destination = (
            development_dependencies
            if group_name.lower() in {"dev", "test", "lint", "quality"}
            else runtime_dependencies
        )

        destination.extend(
            dependency for dependency in dependencies if isinstance(dependency, str)
        )

    poetry_dependencies = poetry.get("dependencies", {})
    if isinstance(poetry_dependencies, dict):
        runtime_dependencies.extend(
            str(name) for name in poetry_dependencies if str(name).lower() != "python"
        )

    poetry_groups = poetry.get("group", {})
    if isinstance(poetry_groups, dict):
        for group_name, group_config in poetry_groups.items():
            if not isinstance(group_config, dict):
                continue

            dependencies = group_config.get("dependencies", {})
            if not isinstance(dependencies, dict):
                continue

            destination = (
                development_dependencies
                if group_name.lower() in {"dev", "test", "lint", "quality"}
                else runtime_dependencies
            )

            destination.extend(str(name) for name in dependencies)

    return {
        "runtime": sorted(set(runtime_dependencies), key=str.lower),
        "development": sorted(set(development_dependencies), key=str.lower),
    }


def inspect_python_file(path: Path) -> PythonFileInfo:
    source = read_text_safely(path)
    line_count = len(source.splitlines())

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return PythonFileInfo(
            path=relative(path),
            lines=line_count,
            classes=0,
            functions=0,
            async_functions=0,
            imports=(),
            syntax_ok=False,
            syntax_error=f"{exc.msg} at line {exc.lineno}",
        )

    classes = 0
    functions = 0
    async_functions = 0
    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes += 1
        elif isinstance(node, ast.AsyncFunctionDef):
            async_functions += 1
        elif isinstance(node, ast.FunctionDef):
            functions += 1
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".", maxsplit=1)[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", maxsplit=1)[0])

    return PythonFileInfo(
        path=relative(path),
        lines=line_count,
        classes=classes,
        functions=functions,
        async_functions=async_functions,
        imports=tuple(sorted(imports)),
        syntax_ok=True,
        syntax_error=None,
    )


def find_shell_files(files: list[Path]) -> list[str]:
    shell_files: list[str] = []

    for path in files:
        suffix = path.suffix.lower()
        first_line = ""

        try:
            with path.open("r", encoding="utf-8", errors="ignore") as file:
                first_line = file.readline().strip()
        except OSError:
            pass

        has_shell_suffix = suffix in SHELL_SUFFIXES
        has_shell_shebang = first_line.startswith("#!") and any(
            shell_name in first_line for shell_name in ("bash", "sh", "zsh", "fish")
        )

        if has_shell_suffix or has_shell_shebang:
            shell_files.append(relative(path))

    return sorted(set(shell_files))


def find_temporary_files(files: list[Path]) -> list[str]:
    findings: list[str] = []

    for path in files:
        if any(pattern.fullmatch(path.name) for pattern in TEMPORARY_FILE_PATTERNS):
            findings.append(relative(path))

    return sorted(findings)


def find_generated_directories(directories: list[Path]) -> list[str]:
    return sorted(
        relative(path) for path in directories if path.name in GENERATED_DIRECTORY_NAMES
    )


def inspect_root_entries() -> dict[str, list[str]]:
    files: list[str] = []
    directories: list[str] = []
    unexpected_files: list[str] = []
    unexpected_directories: list[str] = []

    for entry in sorted(PROJECT_ROOT.iterdir(), key=lambda item: item.name.lower()):
        if entry.name == ".git":
            continue

        if entry.is_file():
            files.append(entry.name)

            if entry.name not in EXPECTED_ROOT_FILES:
                unexpected_files.append(entry.name)

        elif entry.is_dir():
            directories.append(entry.name)

            if (
                entry.name not in LIKELY_SOURCE_DIRECTORIES
                and entry.name not in LIKELY_RUNTIME_DIRECTORIES
                and entry.name
                not in {
                    ".venv",
                    ".github",
                    ".pytest_cache",
                    ".ruff_cache",
                    ".mypy_cache",
                    "__pycache__",
                }
            ):
                unexpected_directories.append(entry.name)

    return {
        "files": files,
        "directories": directories,
        "unexpected_files": unexpected_files,
        "unexpected_directories": unexpected_directories,
    }


def analyze_network_safety(files: list[Path]) -> dict[str, dict[str, Any]]:
    searchable_files = [
        path
        for path in files
        if path.suffix.lower()
        in {
            ".py",
            ".toml",
            ".md",
            ".json",
            ".yaml",
            ".yml",
        }
    ]

    results: dict[str, dict[str, Any]] = {}

    for category, terms in NETWORK_SAFETY_TERMS.items():
        matches: list[dict[str, Any]] = []

        for path in searchable_files:
            source = read_text_safely(path)
            source_lower = source.lower()

            matched_terms = sorted(
                {term for term in terms if term.lower() in source_lower}
            )

            if matched_terms:
                matches.append(
                    {
                        "path": relative(path),
                        "terms": matched_terms,
                    }
                )

        results[category] = {
            "detected": bool(matches),
            "matches": matches,
        }

    return results


def inspect_main_entrypoint() -> dict[str, Any]:
    main_path = PROJECT_ROOT / "main.py"

    result: dict[str, Any] = {
        "exists": main_path.is_file(),
        "accepts_output_argument": False,
        "accepts_url_argument": False,
        "uses_argparse": False,
        "uses_sys_argv": False,
        "has_main_guard": False,
        "references_uv": False,
        "evidence": [],
    }

    if not main_path.is_file():
        return result

    source = read_text_safely(main_path)
    source_lower = source.lower()

    result["uses_argparse"] = "argparse" in source_lower
    result["uses_sys_argv"] = "sys.argv" in source_lower
    result["has_main_guard"] = (
        'if __name__ == "__main__"' in source or "if __name__ == '__main__'" in source
    )
    result["references_uv"] = "uv run" in source_lower

    output_terms = (
        "output_dir",
        "output-dir",
        "output_folder",
        "output-folder",
        "destination",
    )
    url_terms = (
        "start_url",
        "start-url",
        "url",
        "seed_url",
        "seed-url",
    )

    result["accepts_output_argument"] = any(
        term in source_lower for term in output_terms
    )
    result["accepts_url_argument"] = any(term in source_lower for term in url_terms)

    for line_number, line in enumerate(source.splitlines(), start=1):
        lowered_line = line.lower()

        if any(
            marker in lowered_line
            for marker in (
                "argparse",
                "sys.argv",
                "output",
                "start_url",
                "seed_url",
            )
        ):
            result["evidence"].append(
                {
                    "line": line_number,
                    "content": line.strip()[:240],
                }
            )

    result["evidence"] = result["evidence"][:40]
    return result


def inspect_duplicate_logic(files: list[Path]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    terms = (
        "content_hash",
        "sha256",
        "checksum",
        "duplicate",
        "dedup",
        "unique_key",
        "canonical",
        "already_processed",
        "already_seen",
    )

    for path in files:
        if path.suffix.lower() != ".py":
            continue

        source = read_text_safely(path)

        for line_number, line in enumerate(source.splitlines(), start=1):
            lowered_line = line.lower()
            matched_terms = sorted(term for term in terms if term in lowered_line)

            if matched_terms:
                findings.append(
                    {
                        "path": relative(path),
                        "line": line_number,
                        "content": line.strip()[:240],
                        "terms": matched_terms,
                    }
                )

    return findings[:200]


def inspect_locking_and_atomicity(files: list[Path]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    terms = (
        "filelock",
        "portalocker",
        "fcntl",
        "lock",
        "sqlite",
        "transaction",
        "atomic",
        "os.replace",
        "path.replace",
        "tempfile",
    )

    for path in files:
        if path.suffix.lower() != ".py":
            continue

        source = read_text_safely(path)

        for line_number, line in enumerate(source.splitlines(), start=1):
            lowered_line = line.lower()
            matched_terms = sorted(term for term in terms if term in lowered_line)

            if matched_terms:
                findings.append(
                    {
                        "path": relative(path),
                        "line": line_number,
                        "content": line.strip()[:240],
                        "terms": matched_terms,
                    }
                )

    return findings[:200]


def build_module_relationships(
    python_files: list[PythonFileInfo],
) -> dict[str, list[str]]:
    project_module_names: set[str] = set()

    for info in python_files:
        path = Path(info.path)

        if path.name == "__init__.py":
            if len(path.parts) > 1:
                project_module_names.add(path.parts[-2])
        else:
            project_module_names.add(path.stem)

        if path.parts:
            project_module_names.add(path.parts[0])

    relationships: dict[str, list[str]] = {}

    for info in python_files:
        internal_imports = sorted(
            {imported for imported in info.imports if imported in project_module_names}
        )

        relationships[info.path] = internal_imports

    return relationships


def assess_file_responsibilities(
    python_files: list[PythonFileInfo],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    for info in python_files:
        score = 0
        reasons: list[str] = []

        if info.lines > 500:
            score += 3
            reasons.append(f"large file: {info.lines} lines")
        elif info.lines > 300:
            score += 2
            reasons.append(f"moderately large file: {info.lines} lines")

        callable_count = info.functions + info.async_functions

        if callable_count > 20:
            score += 3
            reasons.append(f"many callables: {callable_count}")
        elif callable_count > 12:
            score += 2
            reasons.append(f"multiple callables: {callable_count}")

        if info.classes > 6:
            score += 2
            reasons.append(f"many classes: {info.classes}")

        if len(info.imports) > 20:
            score += 2
            reasons.append(f"many imports: {len(info.imports)}")

        if score:
            findings.append(
                {
                    "path": info.path,
                    "score": score,
                    "reasons": reasons,
                }
            )

    return sorted(
        findings,
        key=lambda item: (-item["score"], item["path"]),
    )


def get_tool_version(executable: str, *arguments: str) -> dict[str, Any]:
    resolved = shutil.which(executable)

    if resolved is None:
        return {
            "installed": False,
            "path": None,
            "version": None,
            "return_code": 127,
        }

    result = run_command((executable, *arguments))

    version_text = result.stdout or result.stderr

    return {
        "installed": result.return_code == 0,
        "path": resolved,
        "version": version_text.splitlines()[0] if version_text else None,
        "return_code": result.return_code,
    }


def inspect_quality_tools(
    dependencies: dict[str, list[str]],
) -> dict[str, Any]:
    all_declared_names = {
        normalize_dependency_name(dependency)
        for dependency in (dependencies["runtime"] + dependencies["development"])
    }

    executable_checks = {
        "uv": get_tool_version("uv", "--version"),
        "python": get_tool_version(sys.executable, "--version"),
        "ruff": get_tool_version("ruff", "--version"),
        "pytest": get_tool_version("pytest", "--version"),
        "mypy": get_tool_version("mypy", "--version"),
        "pre-commit": get_tool_version("pre-commit", "--version"),
        "pip-audit": get_tool_version("pip-audit", "--version"),
        "radon": get_tool_version("radon", "--version"),
    }

    recommended: dict[str, Any] = {}

    for package_name, purpose in RECOMMENDED_DEV_TOOLS.items():
        recommended[package_name] = {
            "purpose": purpose,
            "declared": package_name in all_declared_names,
            "executable_available": executable_checks.get(
                package_name,
                {},
            ).get("installed", False),
        }

    optional: dict[str, Any] = {}

    for package_name, purpose in OPTIONAL_DEV_TOOLS.items():
        optional[package_name] = {
            "purpose": purpose,
            "declared": package_name in all_declared_names,
            "executable_available": executable_checks.get(
                package_name,
                {},
            ).get("installed", False),
        }

    return {
        "executables": executable_checks,
        "recommended": recommended,
        "optional": optional,
    }


def inspect_pyproject_configuration(pyproject: dict[str, Any]) -> dict[str, Any]:
    project = pyproject.get("project", {})
    tool = pyproject.get("tool", {})
    build_system = pyproject.get("build-system", {})

    return {
        "project_name": project.get("name"),
        "project_version": project.get("version"),
        "requires_python": project.get("requires-python"),
        "scripts": project.get("scripts", {}),
        "build_backend": build_system.get("build-backend"),
        "configured_tools": sorted(tool.keys()),
        "has_ruff_config": "ruff" in tool,
        "has_pytest_config": "pytest" in tool,
        "has_mypy_config": "mypy" in tool,
        "has_coverage_config": "coverage" in tool,
    }


def count_suffixes(files: list[Path]) -> list[tuple[str, int]]:
    counts = Counter(
        path.suffix.lower() if path.suffix else "<no suffix>" for path in files
    )

    return sorted(
        counts.items(),
        key=lambda item: (-item[1], item[0]),
    )


def format_code(value: Any) -> str:
    if value is None:
        return "`not detected`"

    text = str(value).replace("`", "\\`")
    return f"`{text}`"


def format_boolean(value: bool) -> str:
    return "Yes" if value else "No"


def markdown_table(
    headers: list[str],
    rows: list[list[Any]],
) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]

    for row in rows:
        normalized_cells = []

        for cell in row:
            text = str(cell)
            text = text.replace("\n", "<br>")
            text = text.replace("|", "\\|")
            normalized_cells.append(text)

        lines.append("| " + " | ".join(normalized_cells) + " |")

    return lines


def render_tree(paths: list[Path]) -> list[str]:
    root_children: dict[tuple[str, ...], set[str]] = defaultdict(set)

    for path in paths:
        parts = path.relative_to(PROJECT_ROOT).parts

        for index, part in enumerate(parts):
            parent = tuple(parts[:index])
            root_children[parent].add(part)

    lines = ["docsync/"]

    def walk(parent: tuple[str, ...], prefix: str) -> None:
        children = sorted(
            root_children.get(parent, set()),
            key=str.lower,
        )

        for index, child in enumerate(children):
            is_last = index == len(children) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{child}")

            child_key = (*parent, child)

            if child_key in root_children:
                next_prefix = prefix + ("    " if is_last else "│   ")
                walk(child_key, next_prefix)

    walk((), "")
    return lines


def build_findings(report: dict[str, Any]) -> list[str]:
    findings: list[str] = []

    pyproject_error = report["pyproject"]["error"]
    if pyproject_error:
        findings.append(f"pyproject problem: {pyproject_error}")

    if report["shell_files"]:
        findings.append(
            "Shell scripts exist even though the target architecture requires "
            "Python-only execution."
        )

    if report["temporary_files"]:
        findings.append("Temporary or backup files were detected.")

    if report["generated_directories"]:
        findings.append("Generated cache directories were detected.")

    syntax_failures = [item for item in report["python_files"] if not item["syntax_ok"]]
    if syntax_failures:
        findings.append("One or more Python files have syntax errors.")

    entrypoint = report["entrypoint"]
    if not entrypoint["exists"]:
        findings.append("Required root entrypoint main.py is missing.")
    else:
        if not entrypoint["accepts_output_argument"]:
            findings.append(
                "main.py does not clearly expose an output-folder argument."
            )
        if not entrypoint["accepts_url_argument"]:
            findings.append("main.py does not clearly expose a start-URL argument.")
        if not entrypoint["has_main_guard"]:
            findings.append("main.py does not contain a standard __main__ guard.")

    safety = report["network_safety"]
    required_safety_categories = (
        "robots",
        "throttling",
        "concurrency",
        "retry_control",
    )

    for category in required_safety_categories:
        if not safety[category]["detected"]:
            findings.append(
                f"Network safety evidence was not detected for: {category}."
            )

    if not safety["duplicate_control"]["detected"]:
        findings.append("Duplicate-control logic was not detected.")

    if not safety["multi_process_safety"]["detected"]:
        findings.append(
            "Cross-process locking or atomic state handling was not detected."
        )

    missing_recommended = [
        name
        for name, state in report["quality_tools"]["recommended"].items()
        if not state["declared"]
    ]

    if missing_recommended:
        findings.append(
            "Recommended development dependencies are missing: "
            + ", ".join(missing_recommended)
            + "."
        )

    if report["responsibility_findings"]:
        findings.append("Some Python modules may contain excessive responsibilities.")

    return findings


def build_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []

    lines.extend(
        [
            "# DOCSYNC Initial Project Audit",
            "",
            f"- Generated: {report['generated_at']}",
            f"- Project root: `{report['project_root']}`",
            f"- Python: `{report['environment']['python_version']}`",
            f"- Platform: `{report['environment']['platform']}`",
            "",
            "## Audit Mode",
            "",
            "This audit is read-only. No project file or directory was deleted.",
            "",
            "## Executive Findings",
            "",
        ]
    )

    if report["findings"]:
        for finding in report["findings"]:
            lines.append(f"- {finding}")
    else:
        lines.append("- No immediate structural findings were detected.")

    lines.extend(
        [
            "",
            "## Root Structure",
            "",
        ]
    )

    root_rows = [
        ["Files", ", ".join(report["root_entries"]["files"]) or "None"],
        [
            "Directories",
            ", ".join(report["root_entries"]["directories"]) or "None",
        ],
        [
            "Unexpected files",
            ", ".join(report["root_entries"]["unexpected_files"]) or "None",
        ],
        [
            "Unexpected directories",
            ", ".join(report["root_entries"]["unexpected_directories"]) or "None",
        ],
    ]
    lines.extend(markdown_table(["Category", "Entries"], root_rows))

    lines.extend(
        [
            "",
            "## Project Tree",
            "",
            "```text",
            *report["project_tree"],
            "```",
            "",
            "## File Type Summary",
            "",
        ]
    )

    lines.extend(
        markdown_table(
            ["Suffix", "Count"],
            [[suffix, count] for suffix, count in report["file_suffix_counts"]],
        )
    )

    lines.extend(
        [
            "",
            "## pyproject.toml Analysis",
            "",
        ]
    )

    pyproject_config = report["pyproject"]["configuration"]

    lines.extend(
        markdown_table(
            ["Property", "Value"],
            [
                ["Parse error", pyproject_config.get("error") or "None"],
                [
                    "Project name",
                    pyproject_config.get("project_name") or "Not declared",
                ],
                [
                    "Project version",
                    pyproject_config.get("project_version") or "Not declared",
                ],
                [
                    "Python requirement",
                    pyproject_config.get("requires_python") or "Not declared",
                ],
                [
                    "Build backend",
                    pyproject_config.get("build_backend") or "Not declared",
                ],
                [
                    "Configured tool sections",
                    ", ".join(pyproject_config.get("configured_tools", [])) or "None",
                ],
                [
                    "Ruff configured",
                    format_boolean(pyproject_config.get("has_ruff_config", False)),
                ],
                [
                    "Pytest configured",
                    format_boolean(pyproject_config.get("has_pytest_config", False)),
                ],
                [
                    "Mypy configured",
                    format_boolean(pyproject_config.get("has_mypy_config", False)),
                ],
                [
                    "Coverage configured",
                    format_boolean(pyproject_config.get("has_coverage_config", False)),
                ],
            ],
        )
    )

    lines.extend(
        [
            "",
            "### Runtime Dependencies",
            "",
        ]
    )

    if report["dependencies"]["runtime"]:
        for dependency in report["dependencies"]["runtime"]:
            lines.append(f"- `{dependency}`")
    else:
        lines.append("- None declared.")

    lines.extend(
        [
            "",
            "### Development Dependencies",
            "",
        ]
    )

    if report["dependencies"]["development"]:
        for dependency in report["dependencies"]["development"]:
            lines.append(f"- `{dependency}`")
    else:
        lines.append("- None declared.")

    lines.extend(
        [
            "",
            "## Development Tool Analysis",
            "",
        ]
    )

    tool_rows: list[list[Any]] = []

    for name, state in report["quality_tools"]["recommended"].items():
        tool_rows.append(
            [
                name,
                state["purpose"],
                format_boolean(state["declared"]),
                format_boolean(state["executable_available"]),
                "Recommended",
            ]
        )

    for name, state in report["quality_tools"]["optional"].items():
        tool_rows.append(
            [
                name,
                state["purpose"],
                format_boolean(state["declared"]),
                format_boolean(state["executable_available"]),
                "Optional",
            ]
        )

    lines.extend(
        markdown_table(
            [
                "Tool",
                "Purpose",
                "Declared",
                "Executable",
                "Priority",
            ],
            tool_rows,
        )
    )

    lines.extend(
        [
            "",
            "## Python Module Inventory",
            "",
        ]
    )

    python_rows = []

    for info in report["python_files"]:
        python_rows.append(
            [
                info["path"],
                info["lines"],
                info["classes"],
                info["functions"],
                info["async_functions"],
                "OK" if info["syntax_ok"] else info["syntax_error"],
            ]
        )

    lines.extend(
        markdown_table(
            [
                "Module",
                "Lines",
                "Classes",
                "Functions",
                "Async functions",
                "Syntax",
            ],
            python_rows,
        )
        if python_rows
        else ["No Python files detected."]
    )

    lines.extend(
        [
            "",
            "## Internal Module Relationships",
            "",
            "```mermaid",
            "flowchart TD",
        ]
    )

    relationship_count = 0

    for source_path, imports in report["module_relationships"].items():
        source_id = re.sub(r"[^A-Za-z0-9_]", "_", source_path)

        if not imports:
            lines.append(f'    {source_id}["{source_path}"]')
            continue

        for imported in imports:
            imported_id = re.sub(r"[^A-Za-z0-9_]", "_", imported)
            lines.append(
                f'    {source_id}["{source_path}"] --> {imported_id}["{imported}"]'
            )
            relationship_count += 1

    if not report["module_relationships"]:
        lines.append('    empty["No Python modules detected"]')
    elif relationship_count == 0:
        lines.append('    isolated["No internal imports were detected"]')

    lines.extend(
        [
            "```",
            "",
            "## Architecture Table",
            "",
        ]
    )

    architecture_rows: list[list[Any]] = []

    for directory_name in report["root_entries"]["directories"]:
        if directory_name in LIKELY_SOURCE_DIRECTORIES:
            category = "Source or tooling"
        elif directory_name in LIKELY_RUNTIME_DIRECTORIES:
            category = "Runtime or generated state"
        elif directory_name.startswith("."):
            category = "Development metadata or cache"
        else:
            category = "Unclassified"

        architecture_rows.append(
            [
                directory_name,
                category,
                "Review required" if category == "Unclassified" else "Recognized",
            ]
        )

    lines.extend(
        markdown_table(
            ["Directory", "Likely responsibility", "Status"],
            architecture_rows,
        )
        if architecture_rows
        else ["No root directories detected."]
    )

    lines.extend(
        [
            "",
            "## Entrypoint Contract",
            "",
        ]
    )

    entrypoint = report["entrypoint"]

    lines.extend(
        markdown_table(
            ["Requirement", "Detected"],
            [
                ["Root main.py exists", format_boolean(entrypoint["exists"])],
                [
                    "Output-folder argument",
                    format_boolean(entrypoint["accepts_output_argument"]),
                ],
                [
                    "Start-URL argument",
                    format_boolean(entrypoint["accepts_url_argument"]),
                ],
                [
                    "argparse usage",
                    format_boolean(entrypoint["uses_argparse"]),
                ],
                [
                    "sys.argv usage",
                    format_boolean(entrypoint["uses_sys_argv"]),
                ],
                [
                    "__main__ guard",
                    format_boolean(entrypoint["has_main_guard"]),
                ],
            ],
        )
    )

    lines.extend(
        [
            "",
            "Required final invocation contract:",
            "",
            "```text",
            "uv run python main.py <output-folder> <url>",
            "```",
            "",
            "### Entrypoint Evidence",
            "",
        ]
    )

    if entrypoint["evidence"]:
        lines.extend(
            markdown_table(
                ["Line", "Source"],
                [
                    [item["line"], f"`{item['content']}`"]
                    for item in entrypoint["evidence"]
                ],
            )
        )
    else:
        lines.append("No command-line evidence detected.")

    lines.extend(
        [
            "",
            "## Shell Script Detection",
            "",
        ]
    )

    if report["shell_files"]:
        for shell_file in report["shell_files"]:
            lines.append(f"- `{shell_file}`")
    else:
        lines.append("- No shell scripts detected.")

    lines.extend(
        [
            "",
            "## Cleanup Candidates",
            "",
            "No item in this section was deleted.",
            "",
            "### Generated Directories",
            "",
        ]
    )

    if report["generated_directories"]:
        for path in report["generated_directories"]:
            lines.append(f"- `{path}`")
    else:
        lines.append("- None detected.")

    lines.extend(
        [
            "",
            "### Temporary Files",
            "",
        ]
    )

    if report["temporary_files"]:
        for path in report["temporary_files"]:
            lines.append(f"- `{path}`")
    else:
        lines.append("- None detected.")

    lines.extend(
        [
            "",
            "## Site Safety and Ban-Risk Controls",
            "",
        ]
    )

    safety_rows = []

    for category, state in report["network_safety"].items():
        evidence_paths = sorted({match["path"] for match in state["matches"]})

        safety_rows.append(
            [
                category,
                format_boolean(state["detected"]),
                ", ".join(evidence_paths[:12]) or "None",
            ]
        )

    lines.extend(
        markdown_table(
            ["Control", "Evidence detected", "Files"],
            safety_rows,
        )
    )

    lines.extend(
        [
            "",
            "The final safety review must verify behavior, not only keyword "
            "presence. The crawler should prioritize host protection over "
            "download speed, enforce robots.txt, apply conservative per-host "
            "concurrency, respect crawl-delay when available, use bounded "
            "retries with backoff, and avoid bot-protection bypass behavior.",
            "",
            "## Duplicate Handling Evidence",
            "",
        ]
    )

    duplicate_findings = report["duplicate_findings"]

    if duplicate_findings:
        lines.extend(
            markdown_table(
                ["File", "Line", "Matched terms", "Source"],
                [
                    [
                        item["path"],
                        item["line"],
                        ", ".join(item["terms"]),
                        f"`{item['content']}`",
                    ]
                    for item in duplicate_findings
                ],
            )
        )
    else:
        lines.append("No duplicate-handling evidence detected.")

    lines.extend(
        [
            "",
            "The next phase will trace the exact duplicate lifecycle:",
            "",
            "1. Whether a URL is skipped before download.",
            "2. Whether content is downloaded and hashed again.",
            "3. Whether unchanged content is discarded after hashing.",
            "4. Whether changed content replaces the old record atomically.",
            "5. Whether duplicate state is safe across simultaneous terminals.",
            "",
            "## Multi-Terminal and Atomicity Evidence",
            "",
        ]
    )

    locking_findings = report["locking_findings"]

    if locking_findings:
        lines.extend(
            markdown_table(
                ["File", "Line", "Matched terms", "Source"],
                [
                    [
                        item["path"],
                        item["line"],
                        ", ".join(item["terms"]),
                        f"`{item['content']}`",
                    ]
                    for item in locking_findings
                ],
            )
        )
    else:
        lines.append(
            "No explicit locking, transactional storage, or atomic-write "
            "evidence detected."
        )

    lines.extend(
        [
            "",
            "## Possible Excessive Responsibilities",
            "",
        ]
    )

    responsibility_findings = report["responsibility_findings"]

    if responsibility_findings:
        lines.extend(
            markdown_table(
                ["File", "Risk score", "Reasons"],
                [
                    [
                        item["path"],
                        item["score"],
                        ", ".join(item["reasons"]),
                    ]
                    for item in responsibility_findings
                ],
            )
        )
    else:
        lines.append("No file crossed the initial size and responsibility thresholds.")

    lines.extend(
        [
            "",
            "## Recommended Next Audit Actions",
            "",
            "1. Review this report and classify every root entry.",
            "2. Add missing quality tools through `uv` only.",
            "3. Run compile, lint, formatting, type-check, and test gates.",
            "4. Trace duplicate and incremental-sync behavior.",
            "5. verify cross-process state isolation and atomic writes.",
            "6. Replace all retained Bash automation with Python modules.",
            "7. Remove only confirmed generated, obsolete, or duplicate files.",
            "8. Refactor modules with excessive responsibilities.",
            "9. enforce the single supported CLI contract.",
            "10. perform controlled crawler safety verification.",
            "",
        ]
    )

    return "\n".join(lines)


def main() -> int:
    if not PROJECT_ROOT.is_dir():
        print(
            f"ERROR: project directory does not exist: {PROJECT_ROOT}",
            file=sys.stderr,
        )
        return 2

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    files = list(iter_project_files())
    directories = list(iter_project_directories())

    pyproject, pyproject_error = load_pyproject()
    dependencies = extract_dependencies(pyproject)
    pyproject_configuration = inspect_pyproject_configuration(pyproject)
    pyproject_configuration["error"] = pyproject_error

    python_file_objects = [
        inspect_python_file(path) for path in files if path.suffix.lower() == ".py"
    ]

    python_files = [
        {
            "path": info.path,
            "lines": info.lines,
            "classes": info.classes,
            "functions": info.functions,
            "async_functions": info.async_functions,
            "imports": list(info.imports),
            "syntax_ok": info.syntax_ok,
            "syntax_error": info.syntax_error,
        }
        for info in python_file_objects
    ]

    project_tree_paths = [
        path
        for path in sorted(
            [*directories, *files],
            key=lambda item: relative(item).lower(),
        )
        if not relative(path).startswith("logs/project_audit/")
    ]

    report: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "project_root": str(PROJECT_ROOT),
        "environment": {
            "python_version": sys.version.replace("\n", " "),
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "working_directory": os.getcwd(),
        },
        "pyproject": {
            "error": pyproject_error,
            "configuration": pyproject_configuration,
        },
        "dependencies": dependencies,
        "quality_tools": inspect_quality_tools(dependencies),
        "root_entries": inspect_root_entries(),
        "project_tree": render_tree(project_tree_paths),
        "file_suffix_counts": count_suffixes(files),
        "python_files": python_files,
        "module_relationships": build_module_relationships(python_file_objects),
        "shell_files": find_shell_files(files),
        "temporary_files": find_temporary_files(files),
        "generated_directories": find_generated_directories(directories),
        "entrypoint": inspect_main_entrypoint(),
        "network_safety": analyze_network_safety(files),
        "duplicate_findings": inspect_duplicate_logic(files),
        "locking_findings": inspect_locking_and_atomicity(files),
        "responsibility_findings": assess_file_responsibilities(python_file_objects),
    }

    report["findings"] = build_findings(report)

    markdown = build_markdown(report)

    REPORT_PATH.write_text(markdown + "\n", encoding="utf-8")
    JSON_REPORT_PATH.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    print("DOCSYNC INITIAL PROJECT AUDIT")
    print("=============================")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Python files: {len(python_files)}")
    print(f"All inspected files: {len(files)}")
    print(f"All inspected directories: {len(directories)}")
    print(f"Shell files: {len(report['shell_files'])}")
    print(f"Generated cache directories: {len(report['generated_directories'])}")
    print(f"Temporary files: {len(report['temporary_files'])}")
    print(f"Findings: {len(report['findings'])}")
    print(f"Markdown report: {REPORT_PATH}")
    print(f"JSON report: {JSON_REPORT_PATH}")
    print()

    if report["findings"]:
        print("FINDINGS")
        print("--------")
        for index, finding in enumerate(report["findings"], start=1):
            print(f"{index}. {finding}")
    else:
        print("No immediate findings.")

    print()
    print("FULL MARKDOWN REPORT")
    print("====================")
    print(markdown)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
