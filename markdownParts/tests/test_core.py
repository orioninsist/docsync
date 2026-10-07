from __future__ import annotations

from pathlib import Path

import pytest

from markdown_parts.core import discover_markdown_files, partition_files, split_markdown_directory


def test_discovers_only_lowercase_md_recursively_in_relative_path_order(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    (root / "z").mkdir(parents=True)
    (root / "a").mkdir()

    (root / "z" / "b.md").write_bytes(b"B")
    (root / "a" / "a.md").write_bytes(b"A")
    (root / "root.md").write_bytes(b"R")
    (root / "ignore.txt").write_text("no")
    (root / "upper.MD").write_text("no")

    discovered = discover_markdown_files(root)

    assert [path.relative_to(root).as_posix() for path in discovered] == [
        "a/a.md",
        "root.md",
        "z/b.md",
    ]


def test_partition_is_balanced() -> None:
    files = [Path(f"{index}.md") for index in range(10)]

    groups = partition_files(files, 3)

    assert [len(group) for group in groups] == [4, 3, 3]
    assert [item for group in groups for item in group] == files


def test_rejects_more_parts_than_files() -> None:
    files = [Path("a.md"), Path("b.md")]

    with pytest.raises(ValueError, match="cannot exceed"):
        partition_files(files, 3)


def test_split_preserves_bytes_and_source_files(tmp_path: Path) -> None:
    root = tmp_path / "crawlee.dev"
    nested = root / "nested"
    nested.mkdir(parents=True)

    source_a = root / "a.md"
    source_b = nested / "b.md"
    source_c = nested / "c.md"

    source_a.write_bytes(b"alpha")
    source_b.write_bytes(b"\nbeta\n")
    source_c.write_bytes(b"gamma")

    before = {
        source_a: source_a.read_bytes(),
        source_b: source_b.read_bytes(),
        source_c: source_c.read_bytes(),
    }

    output_dir = tmp_path / "out"
    results = split_markdown_directory(root, 2, output_dir)

    assert [count for _, count in results] == [2, 1]
    assert (output_dir / "crawlee.dev-1.md").read_bytes() == b"alpha\nbeta\n"
    assert (output_dir / "crawlee.dev-2.md").read_bytes() == b"gamma"

    for path, expected in before.items():
        assert path.read_bytes() == expected


def test_existing_output_is_not_overwritten(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    (root / "a.md").write_bytes(b"A")

    output_dir = tmp_path / "out"
    output_dir.mkdir()
    existing = output_dir / "docs-1.md"
    existing.write_bytes(b"KEEP")

    with pytest.raises(FileExistsError):
        split_markdown_directory(root, 1, output_dir)

    assert existing.read_bytes() == b"KEEP"


def test_zero_markdown_files_is_an_error(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    root.mkdir()
    (root / "a.txt").write_text("nothing")

    with pytest.raises(ValueError, match=r"No \.md files"):
        discover_markdown_files(root)
