"""Project-local manifest path model for docsync crawl sources.

This module owns only path derivation for a project workspace. It does not
read, write, crawl, download, or inspect files. Keeping this logic isolated
prevents CLI, discovery, and downloader modules from duplicating path rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SourceManifest:
    """Immutable project-local manifest paths.

    Example for project_name="openai":

        workspace_dir      -> openai/
        seed_file          -> openai/openai.seed.txt
        allow_file         -> openai/openai.allow.txt
        block_file         -> openai/openai.block.txt
        discovery_report   -> openai/openai.discovery.md
        output_dir         -> openai/
    """

    project_name: str
    workspace_dir: Path
    seed_file: Path
    allow_file: Path
    block_file: Path
    discovery_report: Path
    output_dir: Path

    @classmethod
    def from_project_name(
        cls,
        project_name: str,
        *,
        root_dir: Path | str = ".",
    ) -> SourceManifest:
        """Build all manifest paths for a project-local workspace.

        Args:
            project_name: Stable project directory/name, such as "openai".
            root_dir: Base directory where project folders live.

        Raises:
            ValueError: If project_name is empty or unsafe.
        """

        normalized_name = normalize_project_name(project_name)
        root_path = Path(root_dir)
        workspace_dir = root_path / normalized_name

        return cls(
            project_name=normalized_name,
            workspace_dir=workspace_dir,
            seed_file=workspace_dir / f"{normalized_name}.seed.txt",
            allow_file=workspace_dir / f"{normalized_name}.allow.txt",
            block_file=workspace_dir / f"{normalized_name}.block.txt",
            discovery_report=workspace_dir / f"{normalized_name}.discovery.md",
            output_dir=workspace_dir,
        )

    def ensure_workspace(self) -> None:
        """Create the project workspace without creating nested output folders."""

        self.workspace_dir.mkdir(parents=True, exist_ok=True)


def normalize_project_name(project_name: str) -> str:
    """Return a safe project name for local folder and manifest filenames."""

    candidate = project_name.strip()

    if not candidate:
        msg = "project_name must not be empty"
        raise ValueError(msg)

    if candidate in {".", ".."}:
        msg = "project_name must not be '.' or '..'"
        raise ValueError(msg)

    if "/" in candidate or "\\" in candidate:
        msg = "project_name must be a single folder name, not a path"
        raise ValueError(msg)

    if any(char.isspace() for char in candidate):
        msg = "project_name must not contain whitespace"
        raise ValueError(msg)

    return candidate
