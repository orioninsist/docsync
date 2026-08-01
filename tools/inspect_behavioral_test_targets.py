from __future__ import annotations

import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

PROJECT_ROOT: Final = Path(__file__).resolve().parents[1]

EXCLUDED_DIRECTORY_NAMES: Final = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "htmlcov",
    "logs",
    "node_modules",
    "site",
    "tests",
    "tools",
}

PRODUCTION_FILES: Final = (
    PROJECT_ROOT / "main.py",
    PROJECT_ROOT / "tests/test_behavioral_core.py",
    PROJECT_ROOT / "src" / "docsync" / "markdown.py",
)

INTERESTING_NAME_PARTS: Final = {
    "atomic",
    "backoff",
    "canonical",
    "crawl",
    "delay",
    "duplicate",
    "extract",
    "fetch",
    "incremental",
    "markdown",
    "normalize",
    "output",
    "parse",
    "redirect",
    "retry",
    "robot",
    "save",
    "sync",
    "url",
    "validate",
    "write",
}


@dataclass(frozen=True, slots=True)
class ParameterInfo:
    name: str
    kind: str
    annotation: str | None
    has_default: bool


@dataclass(frozen=True, slots=True)
class CallableInfo:
    file: str
    qualified_name: str
    line: int
    end_line: int
    kind: str
    is_async: bool
    decorators: tuple[str, ...]
    parameters: tuple[ParameterInfo, ...]
    return_annotation: str | None
    docstring: str | None
    raises: tuple[str, ...]
    calls: tuple[str, ...]
    score: int


def render_node(node: ast.AST | None) -> str | None:
    if node is None:
        return None

    try:
        return ast.unparse(node)
    except (AttributeError, ValueError):
        return None


def dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id

    if isinstance(node, ast.Attribute):
        parent = dotted_name(node.value)
        if parent is None:
            return node.attr
        return f"{parent}.{node.attr}"

    return None


def discover_python_files() -> list[Path]:
    discovered: set[Path] = {path for path in PRODUCTION_FILES if path.is_file()}

    src_root = PROJECT_ROOT / "src"
    if src_root.is_dir():
        for path in src_root.rglob("*.py"):
            relative = path.relative_to(PROJECT_ROOT)
            if any(part in EXCLUDED_DIRECTORY_NAMES for part in relative.parts):
                continue
            discovered.add(path)

    return sorted(discovered)


def parameter_infos(
    arguments: ast.arguments,
) -> tuple[ParameterInfo, ...]:
    positional = [
        *arguments.posonlyargs,
        *arguments.args,
    ]

    positional_defaults_start = len(positional) - len(arguments.defaults)

    parameters: list[ParameterInfo] = []

    for index, argument in enumerate(positional):
        kind = (
            "positional-only"
            if index < len(arguments.posonlyargs)
            else "positional-or-keyword"
        )
        parameters.append(
            ParameterInfo(
                name=argument.arg,
                kind=kind,
                annotation=render_node(argument.annotation),
                has_default=index >= positional_defaults_start,
            )
        )

    if arguments.vararg is not None:
        parameters.append(
            ParameterInfo(
                name=arguments.vararg.arg,
                kind="variadic-positional",
                annotation=render_node(arguments.vararg.annotation),
                has_default=False,
            )
        )

    for argument, default in zip(
        arguments.kwonlyargs,
        arguments.kw_defaults,
        strict=True,
    ):
        parameters.append(
            ParameterInfo(
                name=argument.arg,
                kind="keyword-only",
                annotation=render_node(argument.annotation),
                has_default=default is not None,
            )
        )

    if arguments.kwarg is not None:
        parameters.append(
            ParameterInfo(
                name=arguments.kwarg.arg,
                kind="variadic-keyword",
                annotation=render_node(arguments.kwarg.annotation),
                has_default=False,
            )
        )

    return tuple(parameters)


def collect_raises(node: ast.AST) -> tuple[str, ...]:
    raised: set[str] = set()

    for child in ast.walk(node):
        if not isinstance(child, ast.Raise):
            continue

        expression = child.exc
        if expression is None:
            raised.add("<reraised>")
            continue

        if isinstance(expression, ast.Call):
            name = dotted_name(expression.func)
        else:
            name = dotted_name(expression)

        raised.add(name or render_node(expression) or "<unknown>")

    return tuple(sorted(raised))


def collect_calls(node: ast.AST) -> tuple[str, ...]:
    calls: set[str] = set()

    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue

        name = dotted_name(child.func)
        if name:
            calls.add(name)

    return tuple(sorted(calls))


def calculate_score(
    *,
    qualified_name: str,
    parameters: tuple[ParameterInfo, ...],
    raises: tuple[str, ...],
    calls: tuple[str, ...],
    docstring: str | None,
) -> int:
    lowered_name = qualified_name.lower()

    score = sum(4 for part in INTERESTING_NAME_PARTS if part in lowered_name)

    score += min(len(parameters), 5)
    score += min(len(raises) * 2, 6)

    boundary_calls = {
        "open",
        "Path.read_text",
        "Path.write_text",
        "Path.replace",
        "Path.rename",
        "os.replace",
        "shutil.move",
        "subprocess.run",
        "urllib.request.urlopen",
    }

    score += sum(
        2
        for call in calls
        if call in boundary_calls or call.endswith((".request", ".fetch"))
    )

    if docstring:
        score += 1

    return score


class CallableCollector(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.class_stack: list[str] = []
        self.callables: list[CallableInfo] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_stack.append(node.name)
        self.generic_visit(node)
        self.class_stack.pop()

    def visit_FunctionDef(
        self,
        node: ast.FunctionDef,
    ) -> None:
        self._record_callable(node, is_async=False)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(
        self,
        node: ast.AsyncFunctionDef,
    ) -> None:
        self._record_callable(node, is_async=True)
        self.generic_visit(node)

    def _record_callable(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        *,
        is_async: bool,
    ) -> None:
        qualified_name = ".".join([*self.class_stack, node.name])

        parameters = parameter_infos(node.args)
        raises = collect_raises(node)
        calls = collect_calls(node)
        docstring = ast.get_docstring(node)

        score = calculate_score(
            qualified_name=qualified_name,
            parameters=parameters,
            raises=raises,
            calls=calls,
            docstring=docstring,
        )

        self.callables.append(
            CallableInfo(
                file=str(self.path.relative_to(PROJECT_ROOT)),
                qualified_name=qualified_name,
                line=node.lineno,
                end_line=node.end_lineno or node.lineno,
                kind=("method" if self.class_stack else "function"),
                is_async=is_async,
                decorators=tuple(
                    filter(
                        None,
                        (render_node(decorator) for decorator in node.decorator_list),
                    )
                ),
                parameters=parameters,
                return_annotation=render_node(node.returns),
                docstring=docstring,
                raises=raises,
                calls=calls,
                score=score,
            )
        )


def inspect_file(path: Path) -> list[CallableInfo]:
    source = path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        raise RuntimeError(
            f"Could not parse {path.relative_to(PROJECT_ROOT)}: {exc}"
        ) from exc

    collector = CallableCollector(path)
    collector.visit(tree)
    return collector.callables


def format_parameter(parameter: ParameterInfo) -> str:
    rendered = parameter.name

    if parameter.annotation:
        rendered += f": {parameter.annotation}"

    if parameter.has_default:
        rendered += " = <default>"

    return rendered


def write_reports(
    callables: list[CallableInfo],
) -> tuple[Path, Path]:
    report_directory = PROJECT_ROOT / "logs" / "testing"
    report_directory.mkdir(parents=True, exist_ok=True)

    json_path = report_directory / "behavioral_test_targets.json"
    text_path = report_directory / "behavioral_test_targets.txt"

    json_path.write_text(
        json.dumps(
            [asdict(item) for item in callables],
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    lines: list[str] = []

    for callable_info in callables:
        parameters = ", ".join(
            format_parameter(parameter) for parameter in callable_info.parameters
        )

        async_prefix = "async " if callable_info.is_async else ""

        return_annotation = (
            f" -> {callable_info.return_annotation}"
            if callable_info.return_annotation
            else ""
        )

        lines.extend(
            [
                "=" * 100,
                (
                    f"SCORE {callable_info.score:02d} | "
                    f"{callable_info.file}:"
                    f"{callable_info.line}-"
                    f"{callable_info.end_line}"
                ),
                (
                    f"{async_prefix}"
                    f"{callable_info.qualified_name}"
                    f"({parameters})"
                    f"{return_annotation}"
                ),
                (
                    "Decorators: "
                    + (
                        ", ".join(callable_info.decorators)
                        if callable_info.decorators
                        else "none"
                    )
                ),
                (
                    "Raises: "
                    + (
                        ", ".join(callable_info.raises)
                        if callable_info.raises
                        else "none"
                    )
                ),
                (
                    "Calls: "
                    + (
                        ", ".join(callable_info.calls)
                        if callable_info.calls
                        else "none"
                    )
                ),
                (
                    "Docstring: "
                    + (
                        callable_info.docstring.replace(
                            "\n",
                            " ",
                        )
                        if callable_info.docstring
                        else "none"
                    )
                ),
                "",
            ]
        )

    text_path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    return json_path, text_path


def main() -> int:
    python_files = discover_python_files()

    if not python_files:
        print("No production Python files were found.")
        return 1

    callables: list[CallableInfo] = []

    for path in python_files:
        callables.extend(inspect_file(path))

    ranked_callables = sorted(
        callables,
        key=lambda item: (
            -item.score,
            item.file,
            item.line,
            item.qualified_name,
        ),
    )

    json_path, text_path = write_reports(ranked_callables)

    print(f"Production files inspected: {len(python_files)}")
    print(f"Callable targets discovered: {len(ranked_callables)}")

    print()
    print("TOP BEHAVIORAL TEST TARGETS")
    print("=" * 100)

    for callable_info in ranked_callables[:40]:
        parameters = ", ".join(parameter.name for parameter in callable_info.parameters)

        print(
            f"[{callable_info.score:02d}] "
            f"{callable_info.file}:"
            f"{callable_info.line} "
            f"{callable_info.qualified_name}"
            f"({parameters})"
        )

    print()
    print("REPORTS")
    print("=" * 100)
    print(json_path)
    print(text_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

IGNORED_MIGRATION_DIRECTORY = ".docsync-migration"
