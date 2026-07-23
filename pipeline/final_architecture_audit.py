"""Audit the pipeline package for final architectural violations."""

from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Sequence

PIPELINE_DIRECTORY: Final = Path(__file__).resolve().parent

SQL_METHOD_NAMES: Final = frozenset(
    {
        "commit",
        "cursor",
        "execute",
        "executemany",
        "rollback",
    }
)

SQL_RECEIVER_NAMES: Final = frozenset(
    {
        "connection",
        "cursor",
        "database",
        "db",
        "executor",
        "sqlite_connection",
    }
)

SQL_ALLOWED_FILE_NAMES: Final = frozenset(
    {
        "file_snapshot_repository.py",
        "flattened_file_repository.py",
        "sqlite_connection.py",
        "sqlite_executor.py",
    }
)

AUDIT_FILE_NAMES: Final = frozenset(
    {
        "final_architecture_audit.py",
        "repository_integration_audit.py",
    }
)

COMMENTED_CODE_PREFIXES: Final = (
    "async def ",
    "class ",
    "def ",
    "from ",
    "if ",
    "import ",
    "raise ",
    "return ",
    "try:",
    "while ",
    "with ",
)


@dataclass(frozen=True, slots=True)
class Violation:
    """Represent one deterministic architecture-audit finding."""

    path: Path
    line: int
    category: str
    detail: str


@dataclass(frozen=True, slots=True)
class ParsedModule:
    """Contain one parsed Python module and its source lines."""

    path: Path
    tree: ast.Module
    lines: tuple[str, ...]


def main() -> int:
    """Run all final architecture checks."""

    modules = load_modules(PIPELINE_DIRECTORY)
    violations = collect_violations(modules)
    print_report(modules, violations)

    return 1 if violations else 0


def load_modules(directory: Path) -> tuple[ParsedModule, ...]:
    """Parse every Python module below the pipeline directory."""

    return tuple(
        parse_module(path)
        for path in sorted(directory.rglob("*.py"))
        if path.name not in AUDIT_FILE_NAMES
    )


def parse_module(path: Path) -> ParsedModule:
    """Read and parse one UTF-8 Python source file."""

    source = path.read_text(encoding="utf-8")

    return ParsedModule(
        path=path,
        tree=ast.parse(source, filename=str(path)),
        lines=tuple(source.splitlines()),
    )


def collect_violations(
    modules: Sequence[ParsedModule],
) -> tuple[Violation, ...]:
    """Collect every supported architectural violation."""

    violations: list[Violation] = []

    for module in modules:
        violations.extend(find_direct_sql_violations(module))
        violations.extend(find_unused_private_definitions(module))
        violations.extend(find_commented_code(module))

    return tuple(sorted(violations, key=violation_sort_key))


def find_direct_sql_violations(
    module: ParsedModule,
) -> tuple[Violation, ...]:
    """Find direct SQLite operations outside approved persistence modules."""

    if module.path.name in SQL_ALLOWED_FILE_NAMES:
        return ()

    return tuple(
        Violation(
            path=module.path,
            line=node.lineno,
            category="DIRECT_SQL",
            detail=ast.unparse(node),
        )
        for node in ast.walk(module.tree)
        if isinstance(node, ast.Call) and is_direct_sql_call(node)
    )


def is_direct_sql_call(node: ast.Call) -> bool:
    """Return whether a call is a likely direct SQLite operation."""

    if not isinstance(node.func, ast.Attribute):
        return False

    if node.func.attr not in SQL_METHOD_NAMES:
        return False

    receiver_name = root_receiver_name(node.func.value)
    return receiver_name in SQL_RECEIVER_NAMES


def root_receiver_name(node: ast.AST) -> str | None:
    """Resolve the left-most receiver name of an attribute expression."""

    current = node

    while isinstance(current, ast.Attribute):
        current = current.value

    if isinstance(current, ast.Name):
        return current.id

    return None


def find_unused_private_definitions(
    module: ParsedModule,
) -> tuple[Violation, ...]:
    """Find private top-level definitions with no references in their module."""

    reference_counts = collect_name_references(module.tree)
    definitions = top_level_private_definitions(module.tree)

    return tuple(
        Violation(
            path=module.path,
            line=definition.lineno,
            category="UNUSED_PRIVATE_DEFINITION",
            detail=definition.name,
        )
        for definition in definitions
        if reference_counts[definition.name] == 0
    )


def collect_name_references(tree: ast.Module) -> Counter[str]:
    """Count loaded names and attribute references in one module."""

    counts: Counter[str] = Counter()

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            counts[node.id] += 1
        elif isinstance(node, ast.Attribute):
            counts[node.attr] += 1

    return counts


def top_level_private_definitions(
    tree: ast.Module,
) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, ...]:
    """Return non-dunder private definitions declared at module level."""

    definition_types = (
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
    )

    return tuple(
        node
        for node in tree.body
        if isinstance(node, definition_types)
        and node.name.startswith("_")
        and not node.name.startswith("__")
    )


def find_commented_code(
    module: ParsedModule,
) -> tuple[Violation, ...]:
    """Find comments that strongly resemble disabled Python statements."""

    violations: list[Violation] = []

    for line_number, line in enumerate(module.lines, start=1):
        content = normalized_comment_content(line)

        if content is None:
            continue

        if resembles_commented_code(content):
            violations.append(
                Violation(
                    path=module.path,
                    line=line_number,
                    category="COMMENTED_CODE",
                    detail=content,
                )
            )

    return tuple(violations)


def normalized_comment_content(line: str) -> str | None:
    """Return normalized comment content or None for non-comment lines."""

    stripped = line.lstrip()

    if not stripped.startswith("#"):
        return None

    content = stripped.removeprefix("#").strip()
    return content or None


def resembles_commented_code(content: str) -> bool:
    """Return whether comment content resembles disabled Python code."""

    if content.startswith(COMMENTED_CODE_PREFIXES):
        return True

    return resembles_assignment(content)


def resembles_assignment(content: str) -> bool:
    """Return whether comment content resembles a simple assignment."""

    if "=" not in content:
        return False

    left_side, _, right_side = content.partition("=")

    if not left_side.strip() or not right_side.strip():
        return False

    return left_side.strip().isidentifier()


def violation_sort_key(
    violation: Violation,
) -> tuple[str, int, str]:
    """Return deterministic ordering for violations."""

    return (
        violation.path.as_posix(),
        violation.line,
        violation.category,
    )


def print_report(
    modules: Sequence[ParsedModule],
    violations: Sequence[Violation],
) -> None:
    """Print a concise final architecture report."""

    print("FINAL PIPELINE ARCHITECTURE AUDIT")
    print("=" * 100)
    print(f"SCANNED MODULES: {len(modules)}")
    print(f"VIOLATIONS: {len(violations)}")

    if not violations:
        print()
        print("RESULT: CLEAN")
        return

    print()

    for violation in violations:
        relative_path = violation.path.relative_to(PIPELINE_DIRECTORY.parent)
        print(
            f"{relative_path}:{violation.line}: "
            f"{violation.category}: {violation.detail}"
        )

    print()
    print("RESULT: VIOLATIONS FOUND")


if __name__ == "__main__":
    raise SystemExit(main())
