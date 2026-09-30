import sys
from pathlib import Path

import markdown_merge.cli as cli
import pytest


def test_cli_derives_name_from_input_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "developers.openai.com"
    input_dir.mkdir()
    (input_dir / "index.md").write_text("# Hello", encoding="utf-8")
    output_root = tmp_path / "markdownMerge"
    monkeypatch.setattr(cli, "MARKDOWN_MERGE_BASE_DIR", output_root)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mdmerge",
            str(input_dir),
            "--token-limit",
            "1000",
            "--reserve-tokens",
            "0",
            "--encoding",
            "o200k_base",
        ],
    )

    cli.main()

    output_dir = output_root / "developers.openai.com"
    assert (output_dir / "developers.openai.com-1.md").exists()


def test_cli_explicit_name_still_overrides_directory_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_dir = tmp_path / "developers.openai.com"
    input_dir.mkdir()
    (input_dir / "index.md").write_text("# Hello", encoding="utf-8")
    output_root = tmp_path / "markdownMerge"
    monkeypatch.setattr(cli, "MARKDOWN_MERGE_BASE_DIR", output_root)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "mdmerge",
            str(input_dir),
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

    cli.main()

    output_dir = output_root / "developers.openai.com"
    assert (output_dir / "developers-1.md").exists()
