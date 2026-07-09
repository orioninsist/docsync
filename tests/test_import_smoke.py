from __future__ import annotations

import importlib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    "tests",
}


def _iter_project_modules() -> list[str]:
    modules: list[str] = []

    for path in PROJECT_ROOT.rglob("*.py"):
        relative = path.relative_to(PROJECT_ROOT)

        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue

        if path.name == "__init__.py":
            module_parts = relative.parent.parts
        else:
            module_parts = relative.with_suffix("").parts

        if not module_parts:
            continue

        modules.append(".".join(module_parts))

    return sorted(set(modules))


def test_all_project_modules_are_importable() -> None:
    failed_imports: list[str] = []

    for module_name in _iter_project_modules():
        try:
            importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001
            failed_imports.append(f"{module_name}: {exc!r}")

    assert failed_imports == []
