#!/usr/bin/env python3
"""Analyze the docsync repository and generate README architecture documentation."""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import tomllib
from collections import defaultdict
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
README_PATH = PROJECT_ROOT / "README.md"
PYPROJECT_PATH = PROJECT_ROOT / "pyproject.toml"

GENERATED_START = "<!-- BEGIN GENERATED ARCHITECTURE -->"
GENERATED_END = "<!-- END GENERATED ARCHITECTURE -->"

IGNORED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "node_modules",
}

RUNTIME_DATA_DIRECTORIES = {
    "data",
    "logs",
    "output",
    "storage",
}

RUNTIME_INVENTORY_LIMIT = 20

RUNTIME_SUMMARY_DIRECTORIES = {
    "data/markdown",
    "data/state",
    "logs",
    "output",
    "storage",
}

GENERATED_ARCHITECTURE_REPORT = "data/architecture-report.json"

TEXT_FILE_SUFFIXES = {
    ".cfg",
    ".css",
    ".csv",
    ".env",
    ".example",
    ".html",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".rst",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

CONFIG_FILENAMES = {
    ".env",
    ".env.example",
    ".gitignore",
    ".python-version",
    "Dockerfile",
    "Makefile",
    "pyproject.toml",
    "uv.lock",
}

MODULE_PURPOSE_HINTS = {
    "__init__.py": "Defines the package boundary and public package metadata.",
    "__main__.py": "Provides execution through `python -m docsync`.",
    "cli.py": "Parses command-line arguments and starts the application.",
    "config.py": "Loads, validates, and exposes application configuration.",
    "crawler.py": "Coordinates crawling, request handling, extraction, and persistence.",
    "extractor.py": "Extracts structured content from downloaded or rendered pages.",
    "exporter.py": "Transforms extracted records and writes output artifacts.",
    "incremental.py": "Tracks content state and skips pages that do not require refresh.",
    "metrics.py": "Collects crawl counters, timings, and completion reporting.",
    "renderer.py": "Renders JavaScript-dependent pages through Playwright.",
    "reporting.py": "Formats runtime summaries and operational reports.",
    "security.py": "Validates URLs and prevents unsafe network access.",
    "sitemap.py": "Discovers crawl targets from XML sitemaps.",
    "throttle.py": "Controls request rate and crawl concurrency.",
    "rate_limit.py": "Controls request rate and crawl concurrency.",
    "models.py": "Defines shared data models and typed structures.",
    "main.py": "Provides a compatibility application entry point.",
    "conftest.py": "Defines shared pytest fixtures and test configuration.",
}


@dataclass(slots=True)
class PythonFileAnalysis:
    path: Path
    module_name: str
    docstring: str = ""
    imports: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    async_functions: list[str] = field(default_factory=list)
    called_names: set[str] = field(default_factory=set)
    main_guard: bool = False
    line_count: int = 0
    parse_error: str | None = None


def relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def iter_project_files() -> Iterable[Path]:
    for path in sorted(PROJECT_ROOT.rglob("*")):
        if not path.is_file():
            continue

        relative_path = path.relative_to(PROJECT_ROOT)
        relative_parts = relative_path.parts
        relative_string = relative_path.as_posix()

        if any(part in IGNORED_DIRECTORIES for part in relative_parts):
            continue

        if relative_string == GENERATED_ARCHITECTURE_REPORT:
            continue

        yield path


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def module_name_from_path(path: Path) -> str:
    relative_path = path.relative_to(PROJECT_ROOT)

    if relative_path.parts[0] == "src" and len(relative_path.parts) > 1:
        parts = list(relative_path.parts[1:])
    else:
        parts = list(relative_path.parts)

    if parts[-1].endswith(".py"):
        parts[-1] = parts[-1][:-3]

    if parts[-1] == "__init__":
        parts.pop()

    return ".".join(parts)


class CallCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.called_names: set[str] = set()

    def visit_Call(self, node: ast.Call) -> Any:
        name = get_expression_name(node.func)
        if name:
            self.called_names.add(name)
        self.generic_visit(node)


def get_expression_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id

    if isinstance(node, ast.Attribute):
        parent = get_expression_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr

    return None


def is_main_guard(node: ast.If) -> bool:
    test = node.test
    if not isinstance(test, ast.Compare):
        return False

    if not isinstance(test.left, ast.Name) or test.left.id != "__name__":
        return False

    if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
        return False

    if len(test.comparators) != 1:
        return False

    comparator = test.comparators[0]
    return isinstance(comparator, ast.Constant) and comparator.value == "__main__"


def analyze_python_file(path: Path) -> PythonFileAnalysis:
    source = read_text(path)
    analysis = PythonFileAnalysis(
        path=path,
        module_name=module_name_from_path(path),
        line_count=len(source.splitlines()),
    )

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as error:
        analysis.parse_error = f"{error.msg} at line {error.lineno}"
        return analysis

    analysis.docstring = ast.get_docstring(tree) or ""

    for node in tree.body:
        if isinstance(node, ast.Import):
            analysis.imports.extend(alias.name for alias in node.names)

        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imported_names = ", ".join(alias.name for alias in node.names)
            analysis.imports.append(
                f"{module}: {imported_names}" if module else imported_names
            )

        elif isinstance(node, ast.ClassDef):
            analysis.classes.append(node.name)

        elif isinstance(node, ast.AsyncFunctionDef):
            analysis.async_functions.append(node.name)

        elif isinstance(node, ast.FunctionDef):
            analysis.functions.append(node.name)

        elif isinstance(node, ast.If) and is_main_guard(node):
            analysis.main_guard = True

    call_collector = CallCollector()
    call_collector.visit(tree)
    analysis.called_names = call_collector.called_names

    return analysis


def load_pyproject() -> dict[str, Any]:
    if not PYPROJECT_PATH.exists():
        return {}

    with PYPROJECT_PATH.open("rb") as file:
        return tomllib.load(file)


def get_project_metadata(pyproject: dict[str, Any]) -> dict[str, Any]:
    project = pyproject.get("project", {})
    description = str(project.get("description", "")).strip()

    if not description or description.lower() == "add your description here":
        description = (
            "Crawls documentation websites with Crawlee for Python, extracts "
            "meaningful page content, exports normalized Markdown, and maintains "
            "incremental synchronization state."
        )

    return {
        "name": project.get("name", PROJECT_ROOT.name),
        "version": project.get("version", "unknown"),
        "description": description,
        "requires_python": project.get("requires-python", "not declared"),
        "dependencies": project.get("dependencies", []),
        "optional_dependencies": project.get("optional-dependencies", {}),
        "scripts": project.get("scripts", {}),
    }


def get_dependency_name(requirement: str) -> str:
    match = re.match(r"^[A-Za-z0-9_.-]+", requirement)
    return match.group(0) if match else requirement


def infer_file_purpose(path: Path, analysis: PythonFileAnalysis | None = None) -> str:
    filename = path.name
    relative_path = relative(path)

    if filename in MODULE_PURPOSE_HINTS:
        return MODULE_PURPOSE_HINTS[filename]

    if relative_path.startswith("tests/"):
        if filename.startswith("test_"):
            target = filename.removeprefix("test_").removesuffix(".py")
            return f"Validates `{target}` behavior and regression contracts."
        if filename.startswith("verify_"):
            target = filename.removeprefix("verify_").removesuffix(".py")
            return f"Runs an integration or live verification workflow for `{target}`."
        return "Supports automated test execution."

    if relative_path.startswith("tools/"):
        return "Provides a development, validation, migration, or maintenance utility."

    if path.suffix == ".py" and analysis is not None:
        if analysis.docstring:
            first_line = analysis.docstring.strip().splitlines()[0].strip()
            if first_line:
                return first_line.rstrip(".")

        names = analysis.classes + analysis.functions + analysis.async_functions
        if names:
            preview = ", ".join(f"`{name}`" for name in names[:4])
            return f"Implements {preview}."

        return "Defines Python application logic."

    if filename == "pyproject.toml":
        return (
            "Defines package metadata, dependencies, command entry points, and tool "
            "configuration."
        )

    if filename == "uv.lock":
        return "Pins exact dependency versions for reproducible environments."

    if filename == ".env.example":
        return "Documents supported environment variables without containing secrets."

    if filename == ".gitignore":
        return "Excludes generated, local, cache, secret, and runtime files from Git."

    if filename == ".python-version":
        return "Selects the default Python interpreter version."

    if filename == "README.md":
        return "Documents project setup, execution, architecture, and maintenance."

    if filename == "TODO.md":
        return "Tracks pending project work when populated."

    if path.suffix in {".json", ".yaml", ".yml", ".toml", ".ini", ".cfg"}:
        return "Stores structured configuration or application data."

    if path.suffix == ".md":
        return "Provides project documentation."

    if path.suffix == ".sh":
        return "Automates a shell-based project workflow."

    return "Project file."


def get_entry_points(
    metadata: dict[str, Any],
    analyses: dict[Path, PythonFileAnalysis],
) -> list[dict[str, str]]:
    entry_points: list[dict[str, str]] = []

    scripts = metadata.get("scripts", {})
    for command, target in sorted(scripts.items()):
        entry_points.append(
            {
                "command": f"uv run {command}",
                "target": str(target),
                "type": "canonical console command",
            }
        )

    main_path = PROJECT_ROOT / "main.py"
    if main_path.exists():
        entry_points.append(
            {
                "command": "uv run python main.py",
                "target": "main.py",
                "type": "compatibility script",
            }
        )

    package_main_paths = [
        path for path in analyses if path.name == "__main__.py" and "src" in path.parts
    ]
    for package_main in sorted(package_main_paths):
        package_name = package_main.parent.name
        entry_points.append(
            {
                "command": f"uv run python -m {package_name}",
                "target": relative(package_main),
                "type": "module command",
            }
        )

    deduplicated: list[dict[str, str]] = []
    seen_commands: set[str] = set()

    for item in entry_points:
        if item["command"] in seen_commands:
            continue
        seen_commands.add(item["command"])
        deduplicated.append(item)

    return deduplicated


def inspect_help(command: str) -> str | None:
    try:
        command_parts = command.split()
        result = subprocess.run(
            [*command_parts, "--help"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    output = (result.stdout or result.stderr).strip()
    if not output:
        return None

    first_lines = output.splitlines()[:16]
    return "\n".join(first_lines)


def categorize_files(files: list[Path]) -> dict[str, list[Path]]:
    categories: dict[str, list[Path]] = defaultdict(list)

    for path in files:
        relative_parts = path.relative_to(PROJECT_ROOT).parts
        top_level = relative_parts[0]

        if top_level == "src":
            categories["Application source"].append(path)
        elif top_level == "tests":
            categories["Tests and verification"].append(path)
        elif top_level == "tools":
            categories["Development tools"].append(path)
        elif top_level in RUNTIME_DATA_DIRECTORIES:
            categories["Runtime data and generated artifacts"].append(path)
        elif len(relative_parts) == 1 and path.name in CONFIG_FILENAMES:
            categories["Project configuration"].append(path)
        elif len(relative_parts) == 1:
            categories["Root files"].append(path)
        else:
            categories["Other project files"].append(path)

    return dict(categories)


def summarize_runtime_directories(files: list[Path]) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []

    for directory_name in sorted(RUNTIME_SUMMARY_DIRECTORIES):
        directory = PROJECT_ROOT / directory_name
        matching_files = [
            path for path in files if path == directory or directory in path.parents
        ]

        if not matching_files and not directory.exists():
            continue

        total_bytes = 0
        suffix_counts: dict[str, int] = defaultdict(int)

        for path in matching_files:
            with suppress(OSError):
                total_bytes += path.stat().st_size

            suffix = path.suffix.lower() or "[no extension]"
            suffix_counts[suffix] += 1

        summaries.append(
            {
                "directory": directory_name,
                "file_count": len(matching_files),
                "total_bytes": total_bytes,
                "suffix_counts": dict(
                    sorted(
                        suffix_counts.items(),
                        key=lambda item: (-item[1], item[0]),
                    )
                ),
            }
        )

    return summaries


def human_size(size_bytes: int) -> str:
    size = float(size_bytes)

    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024.0 or unit == "TiB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0

    return f"{size_bytes} B"


def source_directory_tree(files: list[Path]) -> str:
    architecture_files = [
        path
        for path in files
        if path.relative_to(PROJECT_ROOT).parts[0] not in RUNTIME_DATA_DIRECTORIES
    ]

    runtime_roots = [
        PROJECT_ROOT / directory
        for directory in sorted(RUNTIME_DATA_DIRECTORIES)
        if (PROJECT_ROOT / directory).exists()
    ]

    synthetic_files = list(architecture_files)

    for root in runtime_roots:
        marker = root / "[generated runtime files omitted]"
        synthetic_files.append(marker)

    return render_directory_tree(synthetic_files)


def render_symbol_summary(analysis: PythonFileAnalysis) -> str:
    parts: list[str] = []

    if analysis.classes:
        parts.append("classes: " + ", ".join(f"`{name}`" for name in analysis.classes))

    functions = analysis.functions + analysis.async_functions
    if functions:
        parts.append("functions: " + ", ".join(f"`{name}`" for name in functions[:8]))

    if analysis.main_guard:
        parts.append("directly executable")

    if analysis.parse_error:
        parts.append(f"parse error: {analysis.parse_error}")

    return "; ".join(parts) if parts else "no top-level public symbols detected"


def find_internal_import_edges(
    analyses: dict[Path, PythonFileAnalysis],
) -> dict[str, set[str]]:
    module_names = {
        analysis.module_name for analysis in analyses.values() if analysis.module_name
    }
    edges: dict[str, set[str]] = defaultdict(set)

    for analysis in analyses.values():
        for imported in analysis.imports:
            imported_module = imported.split(":", maxsplit=1)[0].strip()

            for module_name in module_names:
                if module_name != analysis.module_name and (
                    imported_module == module_name
                    or imported_module.startswith(f"{module_name}.")
                    or module_name.startswith(f"{imported_module}.")
                ):
                    edges[analysis.module_name].add(module_name)

    return edges


def infer_flow_modules(
    analyses: dict[Path, PythonFileAnalysis],
    metadata: dict[str, Any],
) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []

    filename_priorities = [
        ("cli.py", "CLI argument parsing and settings initialization"),
        ("config.py", "configuration loading and validation"),
        ("crawler.py", "crawler construction and crawl orchestration"),
        ("security.py", "target URL and network safety checks"),
        ("sitemap.py", "sitemap parsing and URL discovery"),
        ("incremental.py", "refresh decisions and persistent URL state"),
        ("throttle.py", "request pacing"),
        ("rate_limit.py", "request pacing"),
        ("renderer.py", "browser rendering for JavaScript pages"),
        ("extractor.py", "content extraction and normalization"),
        ("exporter.py", "Markdown or structured output generation"),
        ("metrics.py", "metrics collection"),
        ("reporting.py", "final status and summary output"),
    ]

    for filename, description in filename_priorities:
        matching_paths = sorted(path for path in analyses if path.name == filename)
        for path in matching_paths:
            candidates.append((relative(path), description))

    if candidates:
        return candidates

    scripts = metadata.get("scripts", {})
    for command, target in sorted(scripts.items()):
        candidates.append(
            (
                str(target),
                f"console entry point invoked by `uv run {command}`",
            )
        )

    for path, analysis in sorted(analyses.items(), key=lambda item: relative(item[0])):
        if analysis.main_guard:
            candidates.append(
                (
                    relative(path),
                    "directly executable Python entry point",
                )
            )

    return candidates


def render_directory_tree(files: list[Path]) -> str:
    tree: dict[str, Any] = {}

    for path in files:
        parts = path.relative_to(PROJECT_ROOT).parts
        current = tree
        for part in parts:
            current = current.setdefault(part, {})

    lines: list[str] = [f"{PROJECT_ROOT.name}/"]

    def walk(node: dict[str, Any], prefix: str) -> None:
        entries = sorted(node.items())
        for index, (name, children) in enumerate(entries):
            is_last = index == len(entries) - 1
            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{name}")

            if children:
                extension = "    " if is_last else "│   "
                walk(children, prefix + extension)

    walk(tree, "")
    return "\n".join(lines)


def render_architecture_document(
    files: list[Path],
    analyses: dict[Path, PythonFileAnalysis],
    pyproject: dict[str, Any],
) -> str:
    metadata = get_project_metadata(pyproject)
    entry_points = get_entry_points(metadata, analyses)
    categories = categorize_files(files)
    flow_modules = infer_flow_modules(analyses, metadata)
    import_edges = find_internal_import_edges(analyses)

    source_files = [
        path
        for path in files
        if relative(path).startswith("src/") and path.suffix == ".py"
    ]
    test_files = [
        path
        for path in files
        if relative(path).startswith("tests/") and path.suffix == ".py"
    ]

    lines: list[str] = [
        GENERATED_START,
        "",
        "# docsync Architecture and Operation Guide",
        "",
        "> This section is generated by `tools/update_readme_architecture.py`.",
        "> Run `uv run python tools/update_readme_architecture.py` after architectural changes.",
        "",
        "## 1. Project Purpose",
        "",
        (
            f"`{metadata['name']}` is a Python project that crawls OpenAI web pages, "
            "processes their content, and persists synchronized documentation artifacts."
        ),
    ]

    if metadata["description"]:
        lines.extend(["", metadata["description"]])

    lines.extend(
        [
            "",
            "### Project metadata",
            "",
            f"- Package name: `{metadata['name']}`",
            f"- Version: `{metadata['version']}`",
            f"- Required Python: `{metadata['requires_python']}`",
            f"- Python source files: `{len(source_files)}`",
            f"- Test and verification files: `{len(test_files)}`",
            f"- Total analyzed files: `{len(files)}`",
            "",
            "## 2. Installation",
            "",
            "Install the locked project environment:",
            "",
            "```bash",
            "cd /mnt/local/areas/docsync",
            "uv sync --all-extras",
            "```",
            "",
            "When browser rendering is enabled, install the Playwright browser:",
            "",
            "```bash",
            "cd /mnt/local/areas/docsync",
            "uv run playwright install chromium",
            "```",
            "",
            "Copy the environment template before changing runtime configuration:",
            "",
            "```bash",
            "cd /mnt/local/areas/docsync",
            "cp -n .env.example .env",
            "```",
            "",
            "## 3. How to Run the Project",
            "",
        ]
    )

    if entry_points:
        canonical_entry = entry_points[0]
        lines.extend(
            [
                "The primary detected execution command is:",
                "",
                "```bash",
                "cd /mnt/local/areas/docsync",
                canonical_entry["command"],
                "```",
                "",
                "Detected application entry points:",
                "",
                "| Command | Target | Role |",
                "|---|---|---|",
            ]
        )

        for entry_point in entry_points:
            lines.append(
                f"| `{entry_point['command']}` | `{entry_point['target']}` "
                f"| {entry_point['type']} |"
            )
    else:
        lines.extend(
            [
                "No packaged console command was detected. Use the root compatibility script:",
                "",
                "```bash",
                "cd /mnt/local/areas/docsync",
                "uv run python main.py",
                "```",
            ]
        )

    lines.extend(
        [
            "",
            "### Useful validation commands",
            "",
            "```bash",
            "cd /mnt/local/areas/docsync",
            "",
            "# Show CLI options",
        ]
    )

    if entry_points:
        lines.append(f"{entry_points[0]['command']} --help")
    else:
        lines.append("uv run python main.py --help")

    lines.extend(
        [
            "",
            "# Run the complete test suite",
            "uv run pytest",
            "",
            "# Run static checks",
            "uv run ruff format --check .",
            "uv run ruff check .",
            "uv run mypy src tests",
            "",
            "# Compile Python files",
            "uv run python -m compileall -q src tests tools main.py",
            "```",
            "",
            "## 4. End-to-End Runtime Flow",
            "",
        ]
    )

    if flow_modules:
        for index, (module_path, description) in enumerate(flow_modules, start=1):
            lines.append(f"{index}. `{module_path}` — {description}.")
    else:
        lines.append(
            "1. The detected executable module initializes the package and starts the crawl."
        )

    lines.extend(
        [
            "",
            "### Expected lifecycle",
            "",
            "```text",
            "CLI invocation",
            "    ↓",
            "Configuration and environment loading",
            "    ↓",
            "Crawler initialization",
            "    ↓",
            "Seed URL and sitemap discovery",
            "    ↓",
            "URL validation and request throttling",
            "    ↓",
            "HTTP download or Playwright browser rendering",
            "    ↓",
            "HTML parsing and content extraction",
            "    ↓",
            "Incremental refresh decision and content hashing",
            "    ↓",
            "Markdown or structured artifact export",
            "    ↓",
            "Persistent crawl state update",
            "    ↓",
            "Metrics and completion reporting",
            "```",
            "",
            "A normal run is complete only when the selected CLI command exits. "
            "The crawler may legitimately spend time waiting for rate limits, browser "
            "network-idle conditions, retries, or pending request queue work.",
            "",
            "## 5. Can the Main Command Run From Start to Finish?",
            "",
            "The repository contains the structural components required for an end-to-end run:",
            "",
            "- packaged or script-based application entry points;",
            "- dependency and tool configuration in `pyproject.toml`;",
            "- a locked environment in `uv.lock`;",
            "- application code under `src/`;",
            "- automated tests under `tests/`;",
            "- runtime directories for state, logs, data, and output;",
            "- optional browser-rendering support when configured.",
            "",
            "Before a production crawl, verify all of the following:",
            "",
            "```bash",
            "cd /mnt/local/areas/docsync",
            "uv sync --all-extras",
            "uv run ruff format --check .",
            "uv run ruff check .",
            "uv run mypy src tests",
            "uv run pytest",
            "```",
            "",
            "A successful static and test validation confirms code integrity. "
            "A real crawl additionally depends on network access, valid target URLs, "
            "environment configuration, filesystem permissions, and an installed "
            "Playwright browser when browser mode is used.",
            "",
            "## 6. Directory Architecture",
            "",
            "```text",
            source_directory_tree(files),
            "```",
            "",
            "### Directory responsibilities",
            "",
            "| Directory | Responsibility |",
            "|---|---|",
            "| `src/` | Installable application package and production logic. |",
            "| `tests/` | Unit, integration, regression, and live verification code. |",
            "| `tools/` | Development, migration, inspection, and maintenance scripts. |",
            "| `data/` | Input datasets or crawl-related data files. |",
            "| `storage/` | Crawlee request queues, datasets, key-value state, or durable crawl storage. |",
            "| `output/` | Generated documentation or exported crawl results. |",
            "| `logs/` | Runtime logs and diagnostic output. |",
            "| `.venv/` | Local Python virtual environment managed by `uv`. |",
            "",
            "## 7. File-by-File Responsibilities",
            "",
        ]
    )

    category_order = [
        "Application source",
        "Tests and verification",
        "Development tools",
        "Project configuration",
        "Root files",
        "Runtime data and generated artifacts",
        "Other project files",
    ]

    for category in category_order:
        category_files = categories.get(category)
        if not category_files:
            continue

        if category == "Runtime data and generated artifacts":
            runtime_summaries = summarize_runtime_directories(files)

            lines.extend(
                [
                    f"### {category}",
                    "",
                    "Generated crawl artifacts are summarized by directory rather "
                    "than listed individually. These files are runtime data, not "
                    "application architecture.",
                    "",
                    "| Directory | Files | Size | File types |",
                    "|---|---:|---:|---|",
                ]
            )

            for summary in runtime_summaries:
                suffix_counts = summary["suffix_counts"]
                rendered_types = ", ".join(
                    f"`{suffix}`: {count}"
                    for suffix, count in list(suffix_counts.items())[
                        :RUNTIME_INVENTORY_LIMIT
                    ]
                )

                lines.append(
                    f"| `{summary['directory']}/` "
                    f"| {summary['file_count']} "
                    f"| {human_size(int(summary['total_bytes']))} "
                    f"| {rendered_types or 'none'} |"
                )

            lines.append("")
            continue

        lines.extend(
            [
                f"### {category}",
                "",
                "| File | Responsibility | Main symbols or details |",
                "|---|---|---|",
            ]
        )

        for path in category_files:
            path_string = relative(path)
            analysis = analyses.get(path)
            purpose = infer_file_purpose(path, analysis).replace("|", "\\|")

            if analysis is not None:
                details = render_symbol_summary(analysis)
                details += f"; {analysis.line_count} lines"
            else:
                try:
                    size = path.stat().st_size
                    details = f"{size:,} bytes"
                except OSError:
                    details = "size unavailable"

            lines.append(
                f"| `{path_string}` | {purpose} | {details.replace('|', '\\|')} |"
            )

        lines.append("")

    lines.extend(
        [
            "## 8. Internal Python Module Relationships",
            "",
        ]
    )

    if import_edges:
        lines.extend(
            [
                "| Module | Imports internal modules |",
                "|---|---|",
            ]
        )

        for source_module in sorted(import_edges):
            targets = ", ".join(
                f"`{target}`" for target in sorted(import_edges[source_module])
            )
            lines.append(f"| `{source_module}` | {targets} |")
    else:
        lines.append(
            "No internal import relationships could be inferred from static imports."
        )

    dependencies = metadata.get("dependencies", [])
    optional_dependencies = metadata.get("optional_dependencies", {})

    lines.extend(
        [
            "",
            "## 9. Main Dependencies",
            "",
        ]
    )

    if dependencies:
        lines.extend(
            [
                "| Dependency | Declared requirement |",
                "|---|---|",
            ]
        )
        for dependency in dependencies:
            lines.append(f"| `{get_dependency_name(dependency)}` | `{dependency}` |")
    else:
        lines.append("No runtime dependencies were declared in `pyproject.toml`.")

    if optional_dependencies:
        lines.extend(
            [
                "",
                "### Optional dependency groups",
                "",
                "| Group | Dependencies |",
                "|---|---|",
            ]
        )
        for group_name, group_dependencies in sorted(optional_dependencies.items()):
            rendered_dependencies = ", ".join(
                f"`{get_dependency_name(dependency)}`"
                for dependency in group_dependencies
            )
            lines.append(f"| `{group_name}` | {rendered_dependencies} |")

    lines.extend(
        [
            "",
            "## 10. Runtime Files and State",
            "",
            "- Files under `output/`, `logs/`, `storage/`, and portions of `data/` may be generated or modified during execution.",
            "- `storage/` should be treated as crawler state rather than application source.",
            "- `.env` may contain local secrets and must not be committed.",
            "- `.env.example` defines supported configuration keys and should contain no real secrets.",
            "- Persistent state files should be written atomically to avoid corruption after interrupted runs.",
            "",
            "## 11. Development Workflow",
            "",
            "```bash",
            "cd /mnt/local/areas/docsync",
            "",
            "# Synchronize dependencies",
            "uv sync --all-extras",
            "",
            "# Format changed files",
            "uv run ruff format .",
            "",
            "# Lint and type-check",
            "uv run ruff check .",
            "uv run mypy src tests",
            "",
            "# Run tests",
            "uv run pytest",
            "",
            "# Run the crawler",
        ]
    )

    if entry_points:
        lines.append(entry_points[0]["command"])
    else:
        lines.append("uv run python main.py")

    lines.extend(
        [
            "```",
            "",
            "## 12. Regenerating This Architecture Guide",
            "",
            "```bash",
            "cd /mnt/local/areas/docsync",
            "uv run python tools/update_readme_architecture.py",
            "```",
            "",
            "The generator statically inspects:",
            "",
            "- package metadata and console scripts;",
            "- Python imports, classes, functions, async functions, and executable guards;",
            "- source, test, tool, configuration, and runtime files;",
            "- inferred module relationships and the application lifecycle.",
            "",
            GENERATED_END,
            "",
        ]
    )

    return "\n".join(lines)


def update_readme(generated_content: str) -> None:
    existing_content = read_text(README_PATH) if README_PATH.exists() else ""

    marker_pattern = re.compile(
        rf"{re.escape(GENERATED_START)}.*?{re.escape(GENERATED_END)}",
        flags=re.DOTALL,
    )

    if marker_pattern.search(existing_content):
        updated_content = marker_pattern.sub(
            generated_content.strip(),
            existing_content,
        )
    elif existing_content.strip():
        updated_content = (
            existing_content.rstrip() + "\n\n" + generated_content.strip() + "\n"
        )
    else:
        updated_content = generated_content.strip() + "\n"

    README_PATH.write_text(updated_content, encoding="utf-8")


def write_machine_report(
    files: list[Path],
    analyses: dict[Path, PythonFileAnalysis],
    metadata: dict[str, Any],
) -> None:
    report_path = PROJECT_ROOT / "data" / "architecture-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "project": metadata,
        "files": [
            {
                "path": relative(path),
                "size_bytes": path.stat().st_size,
                "purpose": infer_file_purpose(path, analyses.get(path)),
            }
            for path in files
        ],
        "python_modules": [
            {
                "path": relative(path),
                "module": analysis.module_name,
                "docstring": analysis.docstring,
                "imports": analysis.imports,
                "classes": analysis.classes,
                "functions": analysis.functions,
                "async_functions": analysis.async_functions,
                "called_names": sorted(analysis.called_names),
                "main_guard": analysis.main_guard,
                "line_count": analysis.line_count,
                "parse_error": analysis.parse_error,
            }
            for path, analysis in sorted(
                analyses.items(),
                key=lambda item: relative(item[0]),
            )
        ],
    }

    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    os.chdir(PROJECT_ROOT)

    files = list(iter_project_files())
    python_paths = [path for path in files if path.suffix == ".py"]
    analyses = {path: analyze_python_file(path) for path in python_paths}

    pyproject = load_pyproject()
    metadata = get_project_metadata(pyproject)

    generated_content = render_architecture_document(
        files=files,
        analyses=analyses,
        pyproject=pyproject,
    )

    update_readme(generated_content)
    write_machine_report(files, analyses, metadata)

    parse_errors = [
        analysis for analysis in analyses.values() if analysis.parse_error is not None
    ]

    print("=" * 100)
    print("DOCSYNC ARCHITECTURE ANALYSIS")
    print("=" * 100)
    print(f"Project root:       {PROJECT_ROOT}")
    print(f"Analyzed files:     {len(files)}")
    print(f"Python files:       {len(python_paths)}")
    print(f"Python parse errors:{len(parse_errors):>6}")
    print(f"README updated:     {README_PATH}")
    print(f"JSON report:        {PROJECT_ROOT / 'data' / 'architecture-report.json'}")

    if parse_errors:
        print("\nPARSE ERRORS")
        print("-" * 100)
        for analysis in parse_errors:
            print(f"{relative(analysis.path)}: {analysis.parse_error}")

    print("\nDETECTED RUN COMMANDS")
    print("-" * 100)
    entry_points = get_entry_points(metadata, analyses)

    if entry_points:
        for entry_point in entry_points:
            print(
                f"{entry_point['command']:<40} "
                f"{entry_point['type']} -> {entry_point['target']}"
            )
    else:
        print("uv run python main.py")

    print("\nVALIDATION COMMANDS")
    print("-" * 100)
    print("uv sync --all-extras")
    print("uv run ruff format --check .")
    print("uv run ruff check .")
    print("uv run mypy src tests")
    print("uv run pytest")

    return 1 if parse_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
