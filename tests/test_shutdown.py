"""Regression tests for DocsSync interruption handling."""

from unittest.mock import AsyncMock, patch

from docsync.cli import main


def test_cli_keyboard_interrupt_returns_130(tmp_path):
    with patch(
        "docsync.cli.run_crawler",
        new_callable=AsyncMock,
        side_effect=KeyboardInterrupt,
    ):
        result = main(
            [
                "sync",
                "https://example.com/",
                "--engine",
                "python",
                "--output-dir",
                str(tmp_path / "output"),
                "--state-dir",
                str(tmp_path / "state"),
            ]
        )

    assert result == 130
