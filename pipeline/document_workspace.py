"""Manage document files inside one dynamically resolved crawler output directory."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Iterable

READ_ONLY_MODE = 0o444
WRITE_MODE = 0o644

OUTPUT_DIRECTORY_NAME = "output"
SOURCES_DIRECTORY_NAME = "sources"
MERGED_DIRECTORY_NAME = "_merged"
MERGED_ALLOWED_DIRECTORY_NAMES = frozenset({"current", "history", "stale"})
LEGACY_MERGE_DATABASE_NAME = ".merge_state.db"


class DocumentWorkspaceError(RuntimeError):
    """Raised when a crawler output workspace cannot be safely managed."""


def resolve_project_directory(path: Path) -> Path:
    """Resolve and validate one crawler output directory."""
    project_directory = path.expanduser().resolve()

    _validate_existing_directory(project_directory)
    _validate_output_directory_name(project_directory)
    _validate_sources_directory_layout(project_directory)

    return project_directory


def find_markdown_files(project_directory: Path) -> tuple[Path, ...]:
    """Return every Markdown file beneath the project directory."""
    return tuple(
        sorted(
            path
            for path in project_directory.rglob("*.md")
            if path.is_file()
        )
    )


def set_file_mode(path: Path, mode: int) -> None:
    """Apply an exact permission mode to one file."""
    try:
        os.chmod(path, mode)
    except OSError as error:
        raise DocumentWorkspaceError(
            f"Could not change file mode for {path}: {error}"
        ) from error


def set_markdown_mode(project_directory: Path, mode: int) -> int:
    """Apply one permission mode to every Markdown file in the workspace."""
    markdown_files = find_markdown_files(project_directory)

    for markdown_file in markdown_files:
        set_file_mode(markdown_file, mode)

    return len(markdown_files)


def remove_file(path: Path) -> None:
    """Remove one file after ensuring that it is writable."""
    if not path.exists():
        return

    _validate_removable_file(path)
    set_file_mode(path, WRITE_MODE)
    _unlink_file(path)


def find_legacy_merged_artifacts(
    project_directory: Path,
) -> tuple[Path, ...]:
    """Find obsolete files left by previous pipeline layouts."""
    merged_artifacts = _find_legacy_artifacts_in_merged_directory(
        project_directory
    )
    database_artifacts = _find_legacy_database_artifacts(project_directory)

    return tuple(sorted(set((*merged_artifacts, *database_artifacts))))


def cleanup_legacy_merged_artifacts(project_directory: Path) -> int:
    """Remove obsolete merged files left by previous pipeline layouts."""
    legacy_artifacts = find_legacy_merged_artifacts(project_directory)

    for artifact in legacy_artifacts:
        remove_file(artifact)

    _remove_empty_legacy_directories(project_directory)

    return len(legacy_artifacts)


def validate_markdown_readonly(project_directory: Path) -> None:
    """Ensure every Markdown file has the exact read-only permission mode."""
    writable_files = tuple(
        markdown_file
        for markdown_file in find_markdown_files(project_directory)
        if _file_mode(markdown_file) != READ_ONLY_MODE
    )

    if writable_files:
        raise DocumentWorkspaceError(
            _format_readonly_validation_error(writable_files)
        )


def _validate_existing_directory(project_directory: Path) -> None:
    """Ensure the resolved path exists and is a directory."""
    if not project_directory.exists():
        raise DocumentWorkspaceError(
            f"Project output directory does not exist: {project_directory}"
        )

    if not project_directory.is_dir():
        raise DocumentWorkspaceError(
            f"Project output path is not a directory: {project_directory}"
        )


def _validate_output_directory_name(project_directory: Path) -> None:
    """Ensure the workspace uses the canonical output directory name."""
    if project_directory.name == OUTPUT_DIRECTORY_NAME:
        return

    raise DocumentWorkspaceError(
        "Project directory must be a crawler output directory named "
        f"'{OUTPUT_DIRECTORY_NAME}': {project_directory}"
    )


def _validate_sources_directory_layout(project_directory: Path) -> None:
    """Ensure the workspace follows sources/<project_name>/output."""
    sources_directory = project_directory.parent.parent

    if sources_directory.name == SOURCES_DIRECTORY_NAME:
        return

    raise DocumentWorkspaceError(
        "Project output directory must follow "
        f"'{SOURCES_DIRECTORY_NAME}/<project_name>/{OUTPUT_DIRECTORY_NAME}': "
        f"{project_directory}"
    )


def _validate_removable_file(path: Path) -> None:
    """Ensure a path represents a removable file."""
    if path.is_file():
        return

    raise DocumentWorkspaceError(
        f"Expected a removable file but found another path type: {path}"
    )


def _unlink_file(path: Path) -> None:
    """Remove one previously validated writable file."""
    try:
        path.unlink()
    except OSError as error:
        raise DocumentWorkspaceError(
            f"Could not remove legacy artifact {path}: {error}"
        ) from error


def _find_legacy_artifacts_in_merged_directory(
    project_directory: Path,
) -> tuple[Path, ...]:
    """Return obsolete artifacts beneath the managed merged directory."""
    merged_directory = project_directory / MERGED_DIRECTORY_NAME

    if not merged_directory.exists():
        return ()

    _validate_merged_directory(merged_directory)

    return tuple(
        artifact
        for child in merged_directory.iterdir()
        for artifact in _find_legacy_artifacts_for_child(child)
    )


def _validate_merged_directory(merged_directory: Path) -> None:
    """Ensure the managed merged path is a directory."""
    if merged_directory.is_dir():
        return

    raise DocumentWorkspaceError(
        f"Expected merged directory but found another path type: {merged_directory}"
    )


def _find_legacy_artifacts_for_child(child: Path) -> tuple[Path, ...]:
    """Classify one direct child of the merged directory."""
    if child.is_file():
        return (child,)

    if _is_legacy_directory(child):
        return _find_files_beneath(child)

    return ()


def _is_legacy_directory(path: Path) -> bool:
    """Return whether a directory belongs to an obsolete layout."""
    return (
        path.is_dir()
        and path.name not in MERGED_ALLOWED_DIRECTORY_NAMES
    )


def _find_files_beneath(directory: Path) -> tuple[Path, ...]:
    """Return every regular file beneath one directory."""
    return tuple(
        path
        for path in directory.rglob("*")
        if path.is_file()
    )


def _find_legacy_database_artifacts(
    project_directory: Path,
) -> tuple[Path, ...]:
    """Return the obsolete root-level merge database when present."""
    legacy_database = project_directory / LEGACY_MERGE_DATABASE_NAME

    if legacy_database.is_file():
        return (legacy_database,)

    return ()


def _file_mode(path: Path) -> int:
    """Return the exact permission bits for one file."""
    return stat.S_IMODE(path.stat().st_mode)


def _format_readonly_validation_error(
    writable_files: Iterable[Path],
) -> str:
    """Build the Markdown immutability validation message."""
    formatted_paths = "\n".join(
        f"- {path}" for path in writable_files
    )

    return (
        "Markdown immutability validation failed. "
        "The following files are not mode 0o444:\n"
        f"{formatted_paths}"
    )


def _remove_empty_legacy_directories(project_directory: Path) -> None:
    """Remove empty obsolete directories beneath the merged directory."""
    merged_directory = project_directory / MERGED_DIRECTORY_NAME

    if not merged_directory.is_dir():
        return

    for legacy_directory in _find_legacy_directories(merged_directory):
        _remove_empty_directories_bottom_up(
            legacy_directory.rglob("*"),
            legacy_directory,
        )


def _find_legacy_directories(
    merged_directory: Path,
) -> tuple[Path, ...]:
    """Return obsolete direct child directories."""
    return tuple(
        directory
        for directory in merged_directory.iterdir()
        if _is_legacy_directory(directory)
    )


def _remove_empty_directories_bottom_up(
    descendants: Iterable[Path],
    root_directory: Path,
) -> None:
    """Remove empty directories from deepest descendant to root."""
    directories = sorted(
        (
            path
            for path in descendants
            if path.is_dir()
        ),
        key=lambda path: len(path.parts),
        reverse=True,
    )

    for directory in (*directories, root_directory):
        _remove_directory_if_empty(directory)


def _remove_directory_if_empty(directory: Path) -> None:
    """Remove one directory only when it is empty."""
    try:
        directory.rmdir()
    except OSError:
        return
