from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from docsync.crawler import _atomic_write


def test_atomic_write_creates_file(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "page.md"

    _atomic_write(target, "# Documentation\n")

    assert target.read_text(encoding="utf-8") == "# Documentation\n"
    assert list(target.parent.iterdir()) == [target]


def test_atomic_write_replaces_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "page.md"
    target.write_text("Old content\n", encoding="utf-8")

    _atomic_write(target, "New content\n")

    assert target.read_text(encoding="utf-8") == "New content\n"
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_write_preserves_previous_file_on_failure(
    tmp_path: Path,
) -> None:
    target = tmp_path / "page.md"
    target.write_text("Original content\n", encoding="utf-8")

    with (
        patch(
            "docsync.crawler.os.replace",
            side_effect=OSError("Simulated rename failure"),
        ),
        pytest.raises(OSError, match="Simulated rename failure"),
    ):
        _atomic_write(target, "Incomplete replacement\n")

    assert target.read_text(encoding="utf-8") == "Original content\n"
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_write_does_not_leave_temporary_files(
    tmp_path: Path,
) -> None:
    target = tmp_path / "page.md"

    for index in range(5):
        _atomic_write(target, f"Version {index}\n")

    assert target.read_text(encoding="utf-8") == "Version 4\n"
    assert list(tmp_path.iterdir()) == [target]
