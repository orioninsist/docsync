import sys
from pathlib import Path

import pytest

from markdown_merge.cli import main


def test_cli_derives_name_from_input_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "developers.openai.com"
    output_dir = tmp_path / "merged"

    input_dir.mkdir()
    (input_dir / "index.md").write_text("# Hello", encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mdmerge",
            str(input_dir),
            str(output_dir),
            "--token-limit",
            "1000",
            "--reserve-tokens",
            "0",
            "--encoding",
            "o200k_base",
        ],
    )

    main()

    assert (output_dir / "developers.openai.com-1.md").exists()


def test_cli_explicit_name_still_overrides_directory_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "developers.openai.com"
    output_dir = tmp_path / "merged"

    input_dir.mkdir()
    (input_dir / "index.md").write_text("# Hello", encoding="utf-8")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mdmerge",
            str(input_dir),
            str(output_dir),
            "--name",
            "developers",
            "--token-limit",
            "1000",
            "--reserve-tokens",
            "0",
            "--encoding",
            "o200k_base",
        ],
    )

    main()

    assert (output_dir / "developers-1.md").exists()
