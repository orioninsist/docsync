"""Build a deterministic, read-only inventory of files below ``sources/``.

This module owns only filesystem discovery. It does not read document
contents, calculate fingerprints, access the network, invoke the crawler,
or write pipeline outputs.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Final

DEFAULT_IGNORED_DIRECTORY_NAMES: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
    }
)


@dataclass(frozen=True, slots=True)
class SourceInventoryIssue:
    """Describe one filesystem entry that could not be inventoried safely."""

    path: Path
    reason: str


@dataclass(frozen=True, slots=True)
class SourceInventory:
    """Immutable result of scanning one source root.

    ``files`` contains paths relative to ``root``. Relative paths keep the
    inventory portable and prevent downstream modules from treating arbitrary
    absolute paths as trusted pipeline inputs.
    """

    root: Path
    files: tuple[Path, ...]
    issues: tuple[SourceInventoryIssue, ...]

    @property
    def is_complete(self) -> bool:
        """Return whether the scan completed without filesystem issues."""

        return not self.issues

    @property
    def file_count(self) -> int:
        """Return the number of discovered regular files."""

        return len(self.files)

    def absolute_path(self, relative_path: Path) -> Path:
        """Resolve one inventoried relative path below the source root.

        Raises:
            ValueError: If ``relative_path`` is absolute, escapes the source
                root, or is not present in this inventory.
        """

        normalized_path = _normalize_relative_path(relative_path)

        if normalized_path not in self.files:
            raise ValueError(
                f"Path is not present in the source inventory: {relative_path}"
            )

        return self.root / normalized_path


class SourceInventoryReader:
    """Discover regular files below one source directory without mutation."""

    def __init__(
        self,
        source_root: Path,
        *,
        ignored_directory_names: Iterable[str] = (DEFAULT_IGNORED_DIRECTORY_NAMES),
    ) -> None:
        self._source_root = source_root.expanduser().absolute()
        self._ignored_directory_names = _normalize_ignored_names(
            ignored_directory_names
        )

    def scan(self) -> SourceInventory:
        """Return a deterministic snapshot of regular source files.

        Missing, invalid, unreadable, and unsafe entries are represented as
        issues instead of terminating the entire pipeline.
        """

        root_issue = self._validate_root()
        if root_issue is not None:
            return SourceInventory(
                root=self._source_root,
                files=(),
                issues=(root_issue,),
            )

        discovered_files: list[Path] = []
        issues: list[SourceInventoryIssue] = []

        def record_walk_error(error: OSError) -> None:
            error_path = Path(error.filename) if error.filename else self._source_root
            issues.append(
                SourceInventoryIssue(
                    path=error_path,
                    reason=_format_os_error(error),
                )
            )

        for directory, directory_names, file_names in os.walk(
            self._source_root,
            topdown=True,
            onerror=record_walk_error,
            followlinks=False,
        ):
            directory_path = Path(directory)

            self._filter_directories(
                directory_path=directory_path,
                directory_names=directory_names,
                issues=issues,
            )

            for file_name in sorted(file_names):
                candidate = directory_path / file_name
                self._inspect_file(
                    candidate=candidate,
                    discovered_files=discovered_files,
                    issues=issues,
                )

        discovered_files.sort(key=_path_sort_key)
        issues.sort(
            key=lambda issue: (
                _path_sort_key(issue.path),
                issue.reason,
            )
        )

        return SourceInventory(
            root=self._source_root,
            files=tuple(discovered_files),
            issues=tuple(issues),
        )

    def scan_files(self) -> tuple[Path, ...]:
        """Return only discovered relative file paths.

        Use :meth:`scan` when filesystem issues must also be inspected.
        """

        return self.scan().files

    def _validate_root(self) -> SourceInventoryIssue | None:
        try:
            root_status = self._source_root.lstat()
        except OSError as error:
            return SourceInventoryIssue(
                path=self._source_root,
                reason=_format_os_error(error),
            )

        if stat.S_ISLNK(root_status.st_mode):
            return SourceInventoryIssue(
                path=self._source_root,
                reason="Source root must not be a symbolic link.",
            )

        if not stat.S_ISDIR(root_status.st_mode):
            return SourceInventoryIssue(
                path=self._source_root,
                reason="Source root is not a directory.",
            )

        return None

    def _filter_directories(
        self,
        *,
        directory_path: Path,
        directory_names: list[str],
        issues: list[SourceInventoryIssue],
    ) -> None:
        retained_names: list[str] = []

        for directory_name in sorted(directory_names):
            if directory_name in self._ignored_directory_names:
                continue

            candidate = directory_path / directory_name

            try:
                candidate_status = candidate.lstat()
            except OSError as error:
                issues.append(
                    SourceInventoryIssue(
                        path=candidate,
                        reason=_format_os_error(error),
                    )
                )
                continue

            if stat.S_ISLNK(candidate_status.st_mode):
                issues.append(
                    SourceInventoryIssue(
                        path=candidate,
                        reason="Symbolic-link directories are not followed.",
                    )
                )
                continue

            if not stat.S_ISDIR(candidate_status.st_mode):
                issues.append(
                    SourceInventoryIssue(
                        path=candidate,
                        reason="Directory entry is not a directory.",
                    )
                )
                continue

            retained_names.append(directory_name)

        directory_names[:] = retained_names

    def _inspect_file(
        self,
        *,
        candidate: Path,
        discovered_files: list[Path],
        issues: list[SourceInventoryIssue],
    ) -> None:
        try:
            candidate_status = candidate.lstat()
        except OSError as error:
            issues.append(
                SourceInventoryIssue(
                    path=candidate,
                    reason=_format_os_error(error),
                )
            )
            return

        if stat.S_ISLNK(candidate_status.st_mode):
            issues.append(
                SourceInventoryIssue(
                    path=candidate,
                    reason=("Symbolic-link files are not accepted as source inputs."),
                )
            )
            return

        if not stat.S_ISREG(candidate_status.st_mode):
            issues.append(
                SourceInventoryIssue(
                    path=candidate,
                    reason="Filesystem entry is not a regular file.",
                )
            )
            return

        try:
            relative_path = candidate.relative_to(self._source_root)
        except ValueError:
            issues.append(
                SourceInventoryIssue(
                    path=candidate,
                    reason="Filesystem entry escapes the source root.",
                )
            )
            return

        discovered_files.append(_normalize_relative_path(relative_path))


def build_source_inventory(
    source_root: Path,
    *,
    ignored_directory_names: Iterable[str] = (DEFAULT_IGNORED_DIRECTORY_NAMES),
) -> SourceInventory:
    """Build one immutable inventory using the default reader."""

    return SourceInventoryReader(
        source_root,
        ignored_directory_names=ignored_directory_names,
    ).scan()


def _normalize_ignored_names(names: Iterable[str]) -> frozenset[str]:
    normalized_names: set[str] = set()

    for name in names:
        normalized_name = name.strip()

        if not normalized_name:
            raise ValueError("Ignored directory names must not be empty.")

        if normalized_name in {".", ".."}:
            raise ValueError(f"Unsafe ignored directory name: {normalized_name!r}")

        if "/" in normalized_name or "\\" in normalized_name:
            raise ValueError(
                "Ignored directory names must be individual names, "
                f"not paths: {normalized_name!r}"
            )

        normalized_names.add(normalized_name)

    return frozenset(normalized_names)


def _normalize_relative_path(path: Path) -> Path:
    if path.is_absolute():
        raise ValueError(f"Source inventory paths must be relative: {path}")

    normalized_path = Path(os.path.normpath(path))

    if normalized_path == Path("."):
        raise ValueError("Source inventory paths must identify a file.")

    if normalized_path.parts and normalized_path.parts[0] == "..":
        raise ValueError(f"Source inventory path escapes its root: {path}")

    return normalized_path


def _path_sort_key(path: Path) -> tuple[str, str]:
    portable_path = path.as_posix()
    return portable_path.casefold(), portable_path


def _format_os_error(error: OSError) -> str:
    detail = error.strerror or error.__class__.__name__
    return f"{error.__class__.__name__}: {detail}"
