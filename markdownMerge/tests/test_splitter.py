from pathlib import Path

import pytest
from markdown_merge.splitter import split_files


def test_split_files(tmp_path: Path) -> None:
    file = tmp_path / "test.md"
    file.write_text("# Test\ncontent", encoding="utf-8")

    parts = split_files([file], 100, reserve_tokens=0)

    assert len(parts) == 1
    assert len(parts[0].files) == 1


def test_split_files_uses_relative_source_paths(tmp_path: Path) -> None:
    nested = tmp_path / "guides"
    nested.mkdir()
    file = nested / "setup.md"
    file.write_text("# Setup", encoding="utf-8")

    parts = split_files(
        [file],
        100,
        input_directory=str(tmp_path),
        reserve_tokens=0,
    )

    assert parts[0].files[0].source_path == "guides/setup.md"


def test_split_files_splits_oversized_source(tmp_path: Path) -> None:
    file = tmp_path / "large.md"
    original = ("token " * 100).strip()
    file.write_text(original, encoding="utf-8")

    parts = split_files(
        [file],
        20,
        input_directory=str(tmp_path),
        reserve_tokens=0,
    )

    chunks = [chunk for part in parts for chunk in part.files]

    assert len(chunks) > 1
    assert all(chunk.tokens <= 20 for chunk in chunks)
    assert all(chunk.content is not None for chunk in chunks)
    assert "".join(chunk.content or "" for chunk in chunks) == original
    assert chunks[0].source_path == "large.md [chunk 1]"


def test_split_files_rejects_invalid_reserve() -> None:
    with pytest.raises(ValueError, match="smaller than token_limit"):
        split_files([], 100, reserve_tokens=100)


def test_split_files_uses_first_fit_decreasing(tmp_path: Path) -> None:
    files: list[Path] = []
    for name, repeats in [
        ("a.md", 60),
        ("b.md", 60),
        ("c.md", 40),
        ("d.md", 40),
    ]:
        file = tmp_path / name
        file.write_text(("word " * repeats).strip(), encoding="utf-8")
        files.append(file)

    probe = split_files(
        files,
        10_000,
        input_directory=str(tmp_path),
        reserve_tokens=0,
    )
    weights = {
        chunk.source_path: chunk.tokens for part in probe for chunk in part.files
    }
    capacity = max(
        weights["a.md"] + weights["c.md"],
        weights["b.md"] + weights["d.md"],
    )

    parts = split_files(
        files,
        capacity,
        input_directory=str(tmp_path),
        reserve_tokens=0,
    )

    assert len(parts) == 2
    assert {chunk.source_path for chunk in parts[0].files} == {"a.md", "c.md"}
    assert {chunk.source_path for chunk in parts[1].files} == {"b.md", "d.md"}


def test_split_files_packs_oversized_chunks_with_other_content(tmp_path: Path) -> None:
    large = tmp_path / "large.md"
    small = tmp_path / "small.md"
    large.write_text(("token " * 100).strip(), encoding="utf-8")
    small.write_text("tiny", encoding="utf-8")

    probe = split_files(
        [large, small],
        30,
        input_directory=str(tmp_path),
        reserve_tokens=0,
    )

    assert any(
        len(part.files) > 1 and any(chunk.content is not None for chunk in part.files)
        for part in probe
    )


def test_split_files_is_deterministic_for_equal_sizes(tmp_path: Path) -> None:
    files = []
    for name in ["c.md", "a.md", "b.md"]:
        file = tmp_path / name
        file.write_text("same content", encoding="utf-8")
        files.append(file)

    parts = split_files(
        files,
        10_000,
        input_directory=str(tmp_path),
        reserve_tokens=0,
    )

    assert [chunk.source_path for chunk in parts[0].files] == [
        "a.md",
        "b.md",
        "c.md",
    ]
