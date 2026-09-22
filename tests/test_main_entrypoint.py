"""Behavioral test for the canonical module entry point."""

from __future__ import annotations

import runpy
from pathlib import Path
from unittest.mock import patch


def test_python_module_entrypoint_calls_cli_main() -> None:
    with patch("docsync.cli.main") as mocked_main:
        runpy.run_path(
            str(
                Path(__file__).resolve().parents[1] / "src" / "docsync" / "__main__.py"
            ),
            run_name="__main__",
        )

    mocked_main.assert_called_once_with()
