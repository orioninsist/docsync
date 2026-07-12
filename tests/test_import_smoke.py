"""Verify that every production Python module can be imported safely."""

from __future__ import annotations

import importlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PACKAGE_ROOTS = (
    PROJECT_ROOT / "crawler",
    PROJECT_ROOT / "pipeline",
    PROJECT_ROOT / "tools",
)

TOP_LEVEL_MODULES = (PROJECT_ROOT / "crawler_cli.py",)

EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        "__pycache__",
        "tests",
    }
)


def _module_name_from_path(path: Path) -> str | None:
    relative = path.relative_to(PROJECT_ROOT)

    if any(part in EXCLUDED_DIRECTORY_NAMES for part in relative.parts):
        return None

    if path.name == "__init__.py":
        module_parts = relative.parent.parts
    else:
        module_parts = relative.with_suffix("").parts

    if not module_parts:
        return None

    if not all(part.isidentifier() for part in module_parts):
        return None

    return ".".join(module_parts)


def _iter_package_modules(package_root: Path) -> set[str]:
    if not package_root.is_dir():
        return set()

    modules: set[str] = set()

    for path in package_root.rglob("*.py"):
        if not path.is_file() or path.is_symlink():
            continue

        module_name = _module_name_from_path(path)
        if module_name is not None:
            modules.add(module_name)

    return modules


def _iter_top_level_modules() -> set[str]:
    modules: set[str] = set()

    for path in TOP_LEVEL_MODULES:
        if not path.is_file() or path.is_symlink():
            continue

        module_name = _module_name_from_path(path)
        if module_name is not None:
            modules.add(module_name)

    return modules


def _iter_project_modules() -> list[str]:
    modules = _iter_top_level_modules()

    for package_root in PACKAGE_ROOTS:
        modules.update(_iter_package_modules(package_root))

    return sorted(modules)


def test_all_project_modules_are_importable() -> None:
    """Import every production module without scanning external environments."""
    failed_imports: list[str] = []

    for module_name in _iter_project_modules():
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            failed_imports.append(f"{module_name}: {exc!r}")

    assert not failed_imports, "\n".join(failed_imports)
