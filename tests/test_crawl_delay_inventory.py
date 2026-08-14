"""Inventory contracts for crawl-delay throttling."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "docsync"

IMPLEMENTATION_NAMES = {
    "CrawlDelayThrottle",
    "crawl_delay",
    "delay_seconds",
}

RUNTIME_METHOD_NAMES = {
    "wait",
    "__aenter__",
}


def package_python_files() -> list[Path]:
    """Return production Python files in stable order."""

    return sorted(PACKAGE_ROOT.rglob("*.py"))


def parse_package() -> list[tuple[Path, ast.Module]]:
    """Parse all production modules."""

    parsed: list[tuple[Path, ast.Module]] = []

    for path in package_python_files():
        parsed.append((path, ast.parse(path.read_text(encoding="utf-8"))))

    return parsed


def implementation_references() -> list[str]:
    """Collect crawl-delay implementation references."""

    references: list[str] = []

    for path, tree in parse_package():
        relative_path = path.relative_to(ROOT)

        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in IMPLEMENTATION_NAMES:
                references.append(f"{relative_path}:{node.lineno}:{node.id}")

            if isinstance(node, ast.Attribute) and node.attr in IMPLEMENTATION_NAMES:
                references.append(f"{relative_path}:{node.lineno}:{node.attr}")

            if isinstance(node, ast.ClassDef) and node.name == "CrawlDelayThrottle":
                references.append(f"{relative_path}:{node.lineno}:{node.name}")

    return references


def runtime_references() -> list[str]:
    """Collect executable throttle method references."""

    references: list[str] = []

    for path, tree in parse_package():
        relative_path = path.relative_to(ROOT)

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.AsyncFunctionDef)
                and node.name in RUNTIME_METHOD_NAMES
            ):
                references.append(f"{relative_path}:{node.lineno}:{node.name}")

            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "sleep"
            ):
                references.append(f"{relative_path}:{node.lineno}:{node.func.attr}")

    return references


def test_package_contains_crawl_delay_contract() -> None:
    references = implementation_references()

    assert references, (
        "No crawl-delay, throttling, or rate-limit implementation reference was found."
    )


def test_crawl_delay_has_runtime_behavior() -> None:
    references = runtime_references()

    assert references, "Crawl-delay behavior has no executable wait or sleep reference."


def test_crawl_delay_module_exists() -> None:
    module_path = PACKAGE_ROOT / "crawl_delay.py"

    assert module_path.is_file()
