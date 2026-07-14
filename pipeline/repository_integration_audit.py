"""Audit production modules for required repository integrations."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Sequence

PIPELINE_DIRECTORY: Final = Path(__file__).resolve().parent


@dataclass(frozen=True, slots=True)
class IntegrationTarget:
    """Describe one required production repository integration."""

    file_name: str
    repository_name: str


@dataclass(frozen=True, slots=True)
class RepositoryIntegration:
    """Represent the integration state of one production module."""

    file_name: str
    repository_name: str
    import_found: bool
    instantiation_lines: tuple[int, ...]

    @property
    def is_integrated(self) -> bool:
        """Return whether the repository is imported and instantiated."""

        return self.import_found and bool(self.instantiation_lines)


INTEGRATION_TARGETS: Final = (
    IntegrationTarget(
        file_name="incremental_update.py",
        repository_name="FileSnapshotRepository",
    ),
    IntegrationTarget(
        file_name="flatten_docs.py",
        repository_name="FlattenedFileRepository",
    ),
)


def main() -> int:
    """Run the repository integration audit."""

    integrations = audit_repository_integrations(
        pipeline_directory=PIPELINE_DIRECTORY,
        integration_targets=INTEGRATION_TARGETS,
    )
    print_report(integrations)

    return 0 if all(item.is_integrated for item in integrations) else 1


def audit_repository_integrations(
    *,
    pipeline_directory: Path,
    integration_targets: Sequence[IntegrationTarget],
) -> tuple[RepositoryIntegration, ...]:
    """Audit all required production repository integrations."""

    return tuple(
        audit_target_file(
            pipeline_directory=pipeline_directory,
            target=target,
        )
        for target in integration_targets
    )


def audit_target_file(
    *,
    pipeline_directory: Path,
    target: IntegrationTarget,
) -> RepositoryIntegration:
    """Audit one production module for one repository integration."""

    path = pipeline_directory / target.file_name
    tree = parse_python_file(path)

    return RepositoryIntegration(
        file_name=target.file_name,
        repository_name=target.repository_name,
        import_found=contains_repository_import(
            tree=tree,
            repository_name=target.repository_name,
        ),
        instantiation_lines=find_repository_instantiations(
            tree=tree,
            repository_name=target.repository_name,
        ),
    )


def parse_python_file(path: Path) -> ast.Module:
    """Read and parse one Python source file."""

    source = path.read_text(encoding="utf-8")
    return ast.parse(source, filename=str(path))


def contains_repository_import(
    *,
    tree: ast.Module,
    repository_name: str,
) -> bool:
    """Return whether a module imports the required repository."""

    return any(
        imports_repository(
            node=node,
            repository_name=repository_name,
        )
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    )


def imports_repository(
    *,
    node: ast.Import | ast.ImportFrom,
    repository_name: str,
) -> bool:
    """Return whether one import node exposes the repository name."""

    return any(alias.name == repository_name for alias in node.names)


def find_repository_instantiations(
    *,
    tree: ast.Module,
    repository_name: str,
) -> tuple[int, ...]:
    """Return source lines that instantiate the required repository."""

    return tuple(
        sorted(
            node.lineno
            for node in ast.walk(tree)
            if is_repository_instantiation(
                node=node,
                repository_name=repository_name,
            )
        )
    )


def is_repository_instantiation(
    *,
    node: ast.AST,
    repository_name: str,
) -> bool:
    """Return whether one node constructs the required repository."""

    if not isinstance(node, ast.Call):
        return False

    if isinstance(node.func, ast.Name):
        return node.func.id == repository_name

    if isinstance(node.func, ast.Attribute):
        return node.func.attr == repository_name

    return False


def print_report(
    integrations: Sequence[RepositoryIntegration],
) -> None:
    """Print a deterministic repository integration report."""

    print("REPOSITORY INTEGRATION AUDIT")
    print("=" * 100)

    for integration in integrations:
        print_integration(integration)

    missing = tuple(
        integration
        for integration in integrations
        if not integration.is_integrated
    )

    if not missing:
        print("RESULT: INTEGRATED")
        return

    print("RESULT: NOT INTEGRATED")
    print(
        "MISSING: "
        + ", ".join(
            f"{integration.file_name} -> {integration.repository_name}"
            for integration in missing
        )
    )


def print_integration(integration: RepositoryIntegration) -> None:
    """Print one repository integration result."""

    lines = (
        ", ".join(str(line) for line in integration.instantiation_lines)
        if integration.instantiation_lines
        else "-"
    )

    print()
    print(f"FILE: {integration.file_name}")
    print(f"REPOSITORY: {integration.repository_name}")
    print(f"IMPORT: {'FOUND' if integration.import_found else 'MISSING'}")
    print(f"INSTANTIATION LINES: {lines}")
    print(f"STATUS: {'INTEGRATED' if integration.is_integrated else 'MISSING'}")
    print()
