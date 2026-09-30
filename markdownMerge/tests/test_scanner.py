from pathlib import Path

import pytest

from markdown_merge.scanner import scan_markdown_files


def test_scan_markdown_files(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("# Test", encoding="utf-8")

    files = scan_markdown_files(str(tmp_path))

    assert files == [tmp_path / "a.md"]


def test_scan_markdown_files_rejects_non_directory(tmp_path: Path) -> None:
    file = tmp_path / "a.md"
    file.write_text("# Test", encoding="utf-8")

    with pytest.raises(NotADirectoryError):
        scan_markdown_files(str(file))


def test_scan_markdown_files_can_exclude_directory(tmp_path: Path) -> None:
    included = tmp_path / "docs"
    excluded = tmp_path / "output"
    included.mkdir()
    excluded.mkdir()

    source = included / "a.md"
    generated = excluded / "docs-1.md"
    source.write_text("# Test", encoding="utf-8")
    generated.write_text("# Generated", encoding="utf-8")

    files = scan_markdown_files(
        str(tmp_path),
        exclude_directory=str(excluded),
    )

    assert files == [source]
