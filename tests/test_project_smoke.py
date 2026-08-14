from __future__ import annotations

import ast
import py_compile
import tomllib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

VERIFICATION_SCRIPTS = tuple(
    sorted(
        (PROJECT_ROOT / "tests").glob("verify_*.py"),
        key=lambda path: path.name,
    )
)

PRODUCTION_SOURCES = (
    PROJECT_ROOT / "main.py",
    PROJECT_ROOT / "src" / "docsync" / "markdown.py",
)


def parse_python_file(path: Path) -> ast.Module:
    source = path.read_text(encoding="utf-8")
    return ast.parse(source, filename=str(path))


def top_level_function_names(tree: ast.Module) -> set[str]:
    return {
        node.name
        for node in tree.body
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        )
    }


def test_verification_scripts_exist() -> None:
    assert VERIFICATION_SCRIPTS, "No tests/verify_*.py scripts were found."


@pytest.mark.parametrize(
    "script_path",
    VERIFICATION_SCRIPTS,
    ids=lambda path: path.name,
)
def test_verification_script_has_entrypoint(
    script_path: Path,
) -> None:
    tree = parse_python_file(script_path)
    function_names = top_level_function_names(tree)

    assert "main" in function_names, (
        f"{script_path.relative_to(PROJECT_ROOT)} must expose "
        "a top-level main() entrypoint."
    )


@pytest.mark.parametrize(
    "script_path",
    VERIFICATION_SCRIPTS,
    ids=lambda path: path.name,
)
def test_verification_script_has_main_guard(
    script_path: Path,
) -> None:
    tree = parse_python_file(script_path)

    has_main_guard = any(
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
        and len(node.test.ops) == 1
        and isinstance(node.test.ops[0], ast.Eq)
        and len(node.test.comparators) == 1
        and isinstance(node.test.comparators[0], ast.Constant)
        and node.test.comparators[0].value == "__main__"
        for node in tree.body
    )

    assert has_main_guard, (
        f"{script_path.relative_to(PROJECT_ROOT)} must protect "
        "direct execution with an __main__ guard."
    )


@pytest.mark.parametrize(
    "source_path",
    PRODUCTION_SOURCES,
    ids=lambda path: path.relative_to(PROJECT_ROOT).as_posix(),
)
def test_production_source_compiles(
    source_path: Path,
    tmp_path: Path,
) -> None:
    assert source_path.is_file(), (
        f"Required production source is missing: "
        f"{source_path.relative_to(PROJECT_ROOT)}"
    )

    compiled_path = tmp_path / f"{source_path.stem}.pyc"

    py_compile.compile(
        str(source_path),
        cfile=str(compiled_path),
        doraise=True,
    )

    assert compiled_path.is_file()


def test_pytest_configuration_discovers_test_modules() -> None:
    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    configuration = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    pytest_options = (
        configuration.get("tool", {}).get("pytest", {}).get("ini_options", {})
    )

    testpaths = pytest_options.get("testpaths", [])
    python_files = pytest_options.get("python_files", [])

    assert "tests" in testpaths
    assert "test_*.py" in python_files
