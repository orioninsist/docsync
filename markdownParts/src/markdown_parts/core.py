from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Sequence

DEFAULT_OUTPUT_DIR = Path("/home/murat/Media/8-Document/markdownPart")
_COPY_BUFFER_SIZE = 1024 * 1024


def discover_markdown_files(input_dir: Path) -> list[Path]:
    """Return recursively discovered .md files in deterministic relative-path order."""
    root = input_dir.expanduser().resolve()

    if not root.exists():
        raise ValueError(f"Input directory does not exist: {root}")
    if not root.is_dir():
        raise ValueError(f"Input path is not a directory: {root}")

    files: list[Path] = []
    for current_root, dir_names, file_names in os.walk(root, followlinks=False):
        dir_names.sort()
        file_names.sort()
        current = Path(current_root)

        for name in file_names:
            if Path(name).suffix != ".md":
                continue

            path = current / name
            if path.is_symlink() or not path.is_file():
                continue
            files.append(path)

    files.sort(key=lambda path: path.relative_to(root).as_posix())

    if not files:
        raise ValueError(f"No .md files found under: {root}")

    return files


def partition_files(files: Sequence[Path], parts: int) -> list[list[Path]]:
    """Split files into exactly *parts* groups with size difference at most one."""
    if parts < 1:
        raise ValueError("--parts must be at least 1")
    if parts > len(files):
        raise ValueError(
            f"--parts ({parts}) cannot exceed Markdown file count ({len(files)})"
        )

    base_size, remainder = divmod(len(files), parts)
    groups: list[list[Path]] = []
    start = 0

    for index in range(parts):
        size = base_size + (1 if index < remainder else 0)
        end = start + size
        groups.append(list(files[start:end]))
        start = end

    return groups


def _output_paths(source_name: str, parts: int, output_dir: Path) -> list[Path]:
    return [output_dir / f"{source_name}-{index}.md" for index in range(1, parts + 1)]


def _copy_group(group: Sequence[Path], destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temp_path = Path(temp_name)

    try:
        with os.fdopen(fd, "wb") as output_handle:
            for source_path in group:
                with source_path.open("rb") as input_handle:
                    shutil.copyfileobj(
                        input_handle,
                        output_handle,
                        length=_COPY_BUFFER_SIZE,
                    )
            output_handle.flush()
            os.fsync(output_handle.fileno())

        os.replace(temp_path, destination)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def split_markdown_directory(
    input_dir: Path,
    parts: int,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> list[tuple[Path, int]]:
    """Create exact-count merged Markdown parts without altering source files."""
    source_root = input_dir.expanduser().resolve()
    output_root = output_dir.expanduser().resolve()
    target_root = output_root / source_root.name

    files = discover_markdown_files(source_root)
    groups = partition_files(files, parts)

    target_root.mkdir(parents=True, exist_ok=True)
    destinations = _output_paths(source_root.name, parts, target_root)

    existing = [path for path in destinations if path.exists()]
    if existing:
        joined = ", ".join(str(path) for path in existing)
        raise FileExistsError(f"Output file already exists: {joined}")

    written: list[Path] = []
    try:
        for group, destination in zip(groups, destinations, strict=True):
            _copy_group(group, destination)
            written.append(destination)
    except BaseException:
        for path in written:
            path.unlink(missing_ok=True)
        raise

    return [(path, len(group)) for path, group in zip(destinations, groups, strict=True)]
