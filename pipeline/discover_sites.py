#!/usr/bin/env python3
"""Inspect source workspaces without depending on the crawler package."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCES_ROOT = PROJECT_ROOT / "sources"

SEED_SUFFIX = ".seed.txt"
ALLOW_SUFFIX = ".allow.txt"
SUPPORTED_SUFFIXES = (SEED_SUFFIX, ALLOW_SUFFIX)


class DiscoverSitesArgs(argparse.Namespace):
    """Typed command-line arguments used by the runner."""

    workspace: str | None
    limit: int
    show_files: bool

    def __init__(self) -> None:
        super().__init__()
        self.workspace = None
        self.limit = 50
        self.show_files = False


@dataclass(frozen=True, slots=True)
class SourceWorkspace:
    """A pipeline-visible workspace located below the sources boundary."""

    name: str
    directory: Path
    seed_files: tuple[Path, ...]
    allow_files: tuple[Path, ...]

    @property
    def control_files(self) -> tuple[Path, ...]:
        """Return all source control files in deterministic order."""
        return self.seed_files + self.allow_files


@dataclass(frozen=True, slots=True)
class SourceInventory:
    """URLs discovered from one source workspace."""

    workspace: SourceWorkspace
    seed_urls: tuple[str, ...]
    allow_urls: tuple[str, ...]

    @property
    def urls(self) -> tuple[str, ...]:
        """Return unique URLs while preserving source-file order."""
        return deduplicate(self.seed_urls + self.allow_urls)


def positive_integer(value: str) -> int:
    """Parse a strictly positive command-line integer."""
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"expected an integer, received: {value!r}"
        ) from error

    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be greater than zero")

    return parsed


def parse_args() -> DiscoverSitesArgs:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Inspect crawler-independent source inventories stored below sources/."
        )
    )
    _ = parser.add_argument(
        "workspace",
        nargs="?",
        help=(
            "Source workspace name. When omitted, all available workspaces are listed."
        ),
    )
    _ = parser.add_argument(
        "--limit",
        type=positive_integer,
        default=50,
        help="Maximum number of URLs to display. Default: 50.",
    )
    _ = parser.add_argument(
        "--show-files",
        action="store_true",
        help="Display seed and allow files used by the selected workspace.",
    )
    args = DiscoverSitesArgs()
    return parser.parse_args(namespace=args)


def is_supported_control_file(path: Path) -> bool:
    """Return whether a path is a supported sources control file."""
    return path.is_file() and path.name.endswith(SUPPORTED_SUFFIXES)


def find_control_files(
    directory: Path,
    suffix: str,
) -> tuple[Path, ...]:
    """Find control files directly inside a source workspace."""
    return tuple(
        sorted(
            (
                path
                for path in directory.iterdir()
                if path.is_file() and path.name.endswith(suffix)
            ),
            key=lambda path: path.name.casefold(),
        )
    )


def build_workspace(directory: Path) -> SourceWorkspace:
    """Create a source workspace descriptor."""
    return SourceWorkspace(
        name=directory.name,
        directory=directory,
        seed_files=find_control_files(directory, SEED_SUFFIX),
        allow_files=find_control_files(directory, ALLOW_SUFFIX),
    )


def workspace_has_control_files(workspace: SourceWorkspace) -> bool:
    """Return whether a workspace exposes pipeline-readable control files."""
    return bool(workspace.control_files)


def discover_workspaces(sources_root: Path) -> tuple[SourceWorkspace, ...]:
    """Discover pipeline-visible workspaces below sources/."""
    if not sources_root.is_dir():
        return ()

    workspaces = (
        build_workspace(path)
        for path in sources_root.iterdir()
        if path.is_dir() and not path.name.startswith(".")
    )

    return tuple(
        sorted(
            (
                workspace
                for workspace in workspaces
                if workspace_has_control_files(workspace)
            ),
            key=lambda workspace: workspace.name.casefold(),
        )
    )


def validate_workspace_name(value: str) -> str:
    """Reject URLs, absolute paths, and directory traversal."""
    candidate = value.strip()

    if not candidate:
        raise ValueError("workspace name cannot be empty")

    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        raise ValueError(
            "network discovery is not supported; provide a sources workspace name"
        )

    path = Path(candidate)
    if path.is_absolute() or len(path.parts) != 1 or candidate in {".", ".."}:
        raise ValueError("workspace must be a direct child name below sources/")

    return candidate


def select_workspace(
    workspaces: tuple[SourceWorkspace, ...],
    requested_name: str,
) -> SourceWorkspace:
    """Select one workspace by its exact directory name."""
    normalized_name = validate_workspace_name(requested_name)

    for workspace in workspaces:
        if workspace.name == normalized_name:
            return workspace

    available = ", ".join(workspace.name for workspace in workspaces)
    suffix = f" Available workspaces: {available}" if available else ""
    raise ValueError(f"unknown sources workspace: {normalized_name!r}.{suffix}")


def is_http_url(value: str) -> bool:
    """Return whether a line contains a valid HTTP or HTTPS URL."""
    parsed = urlsplit(value)
    return (
        parsed.scheme.casefold() in {"http", "https"}
        and bool(parsed.netloc)
        and not any(character.isspace() for character in value)
    )


def read_urls(path: Path) -> tuple[str, ...]:
    """Read uncommented HTTP URLs from a UTF-8 control file."""
    urls: list[str] = []

    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        print(f"Warning: unable to read {path}: {error}")
        return ()

    for raw_line in content.splitlines():
        line = raw_line.strip()

        if not line or line.startswith("#"):
            continue

        if is_http_url(line):
            urls.append(line)
        else:
            print(f"Warning: ignored invalid URL in {path}: {line}")

    return tuple(urls)


def read_many(files: tuple[Path, ...]) -> tuple[str, ...]:
    """Read URLs from multiple control files."""
    urls: list[str] = []

    for path in files:
        urls.extend(read_urls(path))

    return tuple(urls)


def deduplicate(values: tuple[str, ...]) -> tuple[str, ...]:
    """Remove duplicate values while preserving their first occurrence."""
    return tuple(dict.fromkeys(values))


def build_inventory(workspace: SourceWorkspace) -> SourceInventory:
    """Build the pipeline inventory for one workspace."""
    return SourceInventory(
        workspace=workspace,
        seed_urls=deduplicate(read_many(workspace.seed_files)),
        allow_urls=deduplicate(read_many(workspace.allow_files)),
    )


def relative_to_project(path: Path) -> str:
    """Format a path relative to the project root when possible."""
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def print_workspace_list(workspaces: tuple[SourceWorkspace, ...]) -> None:
    """Print available pipeline source workspaces."""
    print()
    print("Pipeline Source Workspaces")
    print("--------------------------")
    print(f"Boundary   : {relative_to_project(SOURCES_ROOT)}")
    print(f"Workspaces : {len(workspaces)}")
    print()

    if not workspaces:
        print("No pipeline-readable source workspaces were found.")
        return

    for workspace in workspaces:
        message = "".join(
            (
                f"{workspace.name:<32} ",
                f"seed={len(workspace.seed_files):>2} ",
                f"allow={len(workspace.allow_files):>2}",
            )
        )
        print(message)

    print()
    print("Next:")
    print("python -m pipeline.discover_sites <workspace>")


def print_control_files(workspace: SourceWorkspace) -> None:
    """Print files contributing to a workspace inventory."""
    print()
    print("Control Files")
    print("-------------")

    for path in workspace.control_files:
        print(relative_to_project(path))


def print_inventory(
    inventory: SourceInventory,
    limit: int,
    *,
    show_files: bool,
) -> None:
    """Print one workspace inventory."""
    urls = inventory.urls
    visible_urls = urls[:limit]

    print()
    print("Pipeline Source Inventory")
    print("-------------------------")
    print(f"Workspace    : {inventory.workspace.name}")
    print(f"Directory    : {relative_to_project(inventory.workspace.directory)}")
    print(f"Seed URLs    : {len(inventory.seed_urls)}")
    print(f"Allowed URLs : {len(inventory.allow_urls)}")
    print(f"Unique URLs  : {len(urls)}")
    print(f"Displayed    : {len(visible_urls)}")

    if show_files:
        print_control_files(inventory.workspace)

    print()
    print("URLs")
    print("----")

    if not visible_urls:
        print("No uncommented URLs were found.")
        return

    for index, url in enumerate(visible_urls, start=1):
        print(f"{index:>4}  {url}")

    hidden_count = len(urls) - len(visible_urls)

    if hidden_count > 0:
        print()
        print(f"{hidden_count} additional URL(s) hidden by --limit.")


def run(args: DiscoverSitesArgs) -> int:
    """Execute the sources-only inventory command."""
    workspaces = discover_workspaces(SOURCES_ROOT)

    if args.workspace is None:
        print_workspace_list(workspaces)
        return 0

    try:
        workspace = select_workspace(workspaces, args.workspace)
    except ValueError as error:
        print(f"Error: {error}")
        return 2

    inventory = build_inventory(workspace)
    print_inventory(
        inventory,
        args.limit,
        show_files=args.show_files,
    )
    return 0


def main() -> int:
    """Run the command-line entry point."""
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
