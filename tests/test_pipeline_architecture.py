"""Protect the document pipeline architecture against structural regressions."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PIPELINE_DIRECTORY = Path("pipeline")
PIPELINE_RUNNER_MODULE = Path("pipeline/docs_pipeline_runner.py")
SUBPROCESS_ADAPTER_MODULE = Path("pipeline/subprocess_runner.py")
DOCUMENT_WORKSPACE_MODULE = Path("pipeline/document_workspace.py")

EXPECTED_CLI_ENTRYPOINTS = frozenset(
    {
        Path("pipeline/discover_sites.py"),
        Path("pipeline/docs_pipeline_runner.py"),
        Path("pipeline/flatten_docs.py"),
        Path("pipeline/incremental_update.py"),
        Path("pipeline/merge_service.py"),
        Path("pipeline/release_validate.py"),
        Path("pipeline/run_pipeline.py"),
    }
)

EXPECTED_RUNNER_PIPELINE_IMPORTS = frozenset(
    {
        "pipeline.document_workspace",
        "pipeline.subprocess_runner",
    }
)

FORBIDDEN_ABSOLUTE_OUTPUT_PATHS = frozenset(
    {
        "/output",
        "\\output",
    }
)

READ_ONLY_MODE = 0o444


def pipeline_python_files() -> tuple[Path, ...]:
    """Return every Python module directly owned by the pipeline package."""
    return tuple(sorted(PIPELINE_DIRECTORY.glob("*.py")))


def parse_module(module_path: Path) -> ast.Module:
    """Parse one pipeline module and expose syntax failures clearly."""
    return ast.parse(
        module_path.read_text(encoding="utf-8"),
        filename=str(module_path),
    )


def top_level_function(module: ast.Module, function_name: str) -> ast.FunctionDef:
    """Return one required top-level function from a parsed module."""
    functions = tuple(
        node
        for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )

    assert len(functions) == 1, (
        f"Expected exactly one top-level function named {function_name!r}, "
        f"found {len(functions)}."
    )

    return functions[0]


def imported_pipeline_modules(module: ast.Module) -> frozenset[str]:
    """Return direct pipeline package imports declared by one module."""
    imported_modules: set[str] = set()

    for node in module.body:
        if isinstance(node, ast.Import):
            imported_modules.update(
                alias.name
                for alias in node.names
                if alias.name.startswith("pipeline.")
            )

        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("pipeline."):
                imported_modules.add(node.module)

    return frozenset(imported_modules)


def called_function_names(node: ast.AST) -> tuple[str, ...]:
    """Return direct function names called within one AST node."""
    calls = tuple(
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
    )

    return tuple(
        call.func.id
        for call in sorted(calls, key=lambda item: (item.lineno, item.col_offset))
    )


def referenced_names(node: ast.AST) -> frozenset[str]:
    """Return every variable name referenced within one AST node."""
    return frozenset(
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name)
    )


def is_name_main_comparison(node: ast.AST) -> bool:
    """Return whether an AST node represents ``__name__ == '__main__'``."""
    if not isinstance(node, ast.Compare):
        return False

    if len(node.ops) != 1 or not isinstance(node.ops[0], ast.Eq):
        return False

    if len(node.comparators) != 1:
        return False

    left = node.left
    right = node.comparators[0]

    return (
        isinstance(left, ast.Name)
        and left.id == "__name__"
        and isinstance(right, ast.Constant)
        and right.value == "__main__"
    ) or (
        isinstance(right, ast.Name)
        and right.id == "__name__"
        and isinstance(left, ast.Constant)
        and left.value == "__main__"
    )


def exposes_cli_entrypoint(module: ast.Module) -> bool:
    """Return whether a module intentionally exposes a Python CLI."""
    return any(
        isinstance(node, ast.If) and is_name_main_comparison(node.test)
        for node in ast.walk(module)
    )


def discover_cli_entrypoints() -> frozenset[Path]:
    """Discover pipeline modules containing a real ``__main__`` guard."""
    return frozenset(
        module_path
        for module_path in pipeline_python_files()
        if exposes_cli_entrypoint(parse_module(module_path))
    )


def string_constants(module: ast.Module) -> tuple[str, ...]:
    """Return string literals declared anywhere in one module."""
    return tuple(
        node.value
        for node in ast.walk(module)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


def forbidden_output_path_literals(module_path: Path) -> tuple[str, ...]:
    """Return absolute output-directory literals found in one module."""
    module = parse_module(module_path)

    return tuple(
        value
        for value in string_constants(module)
        if value.strip().lower() in FORBIDDEN_ABSOLUTE_OUTPUT_PATHS
    )


def subprocess_run_calls(module: ast.Module) -> tuple[ast.Call, ...]:
    """Return direct ``subprocess.run`` calls from one module."""
    calls: list[ast.Call] = []

    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue

        function = node.func
        if not isinstance(function, ast.Attribute):
            continue

        if (
            isinstance(function.value, ast.Name)
            and function.value.id == "subprocess"
            and function.attr == "run"
        ):
            calls.append(node)

    return tuple(calls)


def call_uses_check_true(call: ast.Call) -> bool:
    """Return whether a subprocess call explicitly fails on non-zero exit."""
    return any(
        keyword.arg == "check"
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for keyword in call.keywords
    )


def assigned_integer_constants(
    module: ast.Module,
    constant_name: str,
) -> tuple[int, ...]:
    """Return integer values assigned to a named module constant."""
    values: list[int] = []

    for node in module.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue

        targets: tuple[ast.expr, ...]
        value: ast.expr | None

        if isinstance(node, ast.Assign):
            targets = tuple(node.targets)
            value = node.value
        else:
            targets = (node.target,)
            value = node.value

        if value is None:
            continue

        if not isinstance(value, ast.Constant) or not isinstance(value.value, int):
            continue

        if any(
            isinstance(target, ast.Name) and target.id == constant_name
            for target in targets
        ):
            values.append(value.value)

    return tuple(values)


def finally_blocks(function: ast.FunctionDef) -> tuple[ast.Try, ...]:
    """Return try statements containing a finally block."""
    return tuple(
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Try) and node.finalbody
    )


def test_all_pipeline_modules_are_valid_python() -> None:
    """Ensure every pipeline module remains syntactically valid."""
    modules = pipeline_python_files()

    assert modules, "No Python modules were discovered in pipeline/."

    for module_path in modules:
        parse_module(module_path)


def test_pipeline_cli_entrypoints_are_intentional() -> None:
    """Ensure only approved orchestration and service modules expose a CLI."""
    discovered_entrypoints = discover_cli_entrypoints()

    assert discovered_entrypoints == EXPECTED_CLI_ENTRYPOINTS, (
        "Pipeline CLI entrypoints differ from the intentional architecture.\n"
        f"Expected: {sorted(map(str, EXPECTED_CLI_ENTRYPOINTS))}\n"
        f"Actual:   {sorted(map(str, discovered_entrypoints))}"
    )


@pytest.mark.parametrize(
    "module_path",
    pipeline_python_files(),
    ids=lambda path: path.name,
)
def test_pipeline_has_no_absolute_output_directory_literal(
    module_path: Path,
) -> None:
    """Reject static root assumptions such as ``/output``."""
    forbidden_literals = forbidden_output_path_literals(module_path)

    assert not forbidden_literals, (
        f"{module_path} contains forbidden absolute output paths: "
        f"{forbidden_literals}"
    )


@pytest.mark.parametrize(
    "module_path",
    tuple(
        path
        for path in pipeline_python_files()
        if path != SUBPROCESS_ADAPTER_MODULE
    ),
    ids=lambda path: path.name,
)
def test_direct_subprocess_calls_fail_loudly(module_path: Path) -> None:
    """Require subprocess calls outside the adapter to use ``check=True``."""
    module = parse_module(module_path)
    unsafe_calls = tuple(
        call
        for call in subprocess_run_calls(module)
        if not call_uses_check_true(call)
    )

    assert not unsafe_calls, (
        f"{module_path} contains subprocess.run calls without check=True "
        f"at lines {[call.lineno for call in unsafe_calls]}"
    )


def test_subprocess_execution_is_centralized() -> None:
    """Allow controlled ``check=False`` behavior only in the subprocess adapter."""
    modules_with_subprocess_calls = frozenset(
        module_path
        for module_path in pipeline_python_files()
        if subprocess_run_calls(parse_module(module_path))
    )

    allowed_modules = frozenset(
        {
            SUBPROCESS_ADAPTER_MODULE,
            Path("pipeline/run_pipeline.py"),
        }
    )

    assert modules_with_subprocess_calls <= allowed_modules, (
        "Direct subprocess execution escaped the centralized adapter boundary: "
        f"{sorted(map(str, modules_with_subprocess_calls - allowed_modules))}"
    )


def test_subprocess_adapter_captures_process_results() -> None:
    """Require the adapter to retain control over return-code handling."""
    adapter_module = parse_module(SUBPROCESS_ADAPTER_MODULE)
    adapter_calls = subprocess_run_calls(adapter_module)

    assert adapter_calls, "The subprocess adapter contains no subprocess.run calls."

    assert all(not call_uses_check_true(call) for call in adapter_calls), (
        "The subprocess adapter must capture process results before raising "
        "pipeline-specific exceptions."
    )


def test_document_workspace_defines_strict_read_only_mode() -> None:
    """Protect the immutable Markdown output permission contract."""
    workspace_module = parse_module(DOCUMENT_WORKSPACE_MODULE)

    configured_modes = assigned_integer_constants(
        workspace_module,
        "READ_ONLY_MODE",
    )

    assert configured_modes == (READ_ONLY_MODE,), (
        "pipeline/document_workspace.py must define exactly "
        "READ_ONLY_MODE = 0o444."
    )


def test_pipeline_runner_depends_only_on_explicit_boundaries() -> None:
    """Keep orchestration coupled only to workspace and subprocess adapters."""
    runner_module = parse_module(PIPELINE_RUNNER_MODULE)
    imported_modules = imported_pipeline_modules(runner_module)

    assert imported_modules == EXPECTED_RUNNER_PIPELINE_IMPORTS, (
        "docs_pipeline_runner.py crossed an unauthorized pipeline boundary.\n"
        f"Expected: {sorted(EXPECTED_RUNNER_PIPELINE_IMPORTS)}\n"
        f"Actual:   {sorted(imported_modules)}"
    )


def test_pipeline_runner_resolves_scripts_dynamically() -> None:
    """Require script resolution to use its argument and validate existence."""
    runner_module = parse_module(PIPELINE_RUNNER_MODULE)
    resolver = top_level_function(runner_module, "resolve_pipeline_script")

    assert len(resolver.args.args) == 1, (
        "resolve_pipeline_script must accept exactly one script identifier."
    )

    script_argument = resolver.args.args[0].arg
    names = referenced_names(resolver)

    assert script_argument in names, (
        "resolve_pipeline_script must use its script identifier dynamically."
    )

    assert any(
        isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
        for node in ast.walk(resolver)
    ), (
        "resolve_pipeline_script must join the pipeline directory and script "
        "identifier through pathlib path composition."
    )

    assert any(
        isinstance(node, ast.Attribute) and node.attr == "is_file"
        for node in ast.walk(resolver)
    ), "resolve_pipeline_script must verify the resolved script exists."


def test_pipeline_stage_execution_uses_subprocess_adapter() -> None:
    """Require every orchestration stage to execute through run_python_script."""
    runner_module = parse_module(PIPELINE_RUNNER_MODULE)
    executor = top_level_function(runner_module, "execute_pipeline_stage")
    calls = called_function_names(executor)

    assert "run_python_script" in calls, (
        "execute_pipeline_stage must delegate process execution to "
        "pipeline.subprocess_runner.run_python_script."
    )

    assert not subprocess_run_calls(runner_module), (
        "docs_pipeline_runner.py must not execute subprocesses directly."
    )


def test_pipeline_runner_restores_and_validates_read_only_mode() -> None:
    """Guarantee permission restoration and final read-only validation."""
    runner_module = parse_module(PIPELINE_RUNNER_MODULE)
    runner = top_level_function(runner_module, "run_document_pipeline")
    protected_blocks = finally_blocks(runner)

    assert len(protected_blocks) == 1, (
        "run_document_pipeline must contain exactly one try/finally boundary."
    )

    final_calls = called_function_names(
        ast.Module(body=protected_blocks[0].finalbody, type_ignores=[])
    )
    runner_calls = called_function_names(runner)

    assert "set_markdown_mode" in final_calls, (
        "run_document_pipeline must restore Markdown permissions in finally."
    )

    assert "validate_markdown_readonly" in runner_calls, (
        "run_document_pipeline must validate the final Markdown read-only state."
    )
