"""Regression tests for the production entry point."""

from __future__ import annotations

import runpy
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from docsync.config import Settings
from docsync.main import main, run


def _settings() -> Settings:
    return Settings.from_environment()


def test_run_executes_crawler_with_configured_start_url() -> None:
    settings = _settings()
    logger = MagicMock()
    crawler = AsyncMock()

    with (
        patch(
            "docsync.main.Settings.from_environment",
            return_value=settings,
        ),
        patch(
            "docsync.main.configure_logging",
            return_value=logger,
        ),
        patch(
            "docsync.main.run_crawler",
            crawler,
        ),
    ):
        result = run()

    assert result == 0
    crawler.assert_awaited_once_with(settings.start_url)


def test_run_returns_one_for_startup_error() -> None:
    with patch(
        "docsync.main.Settings.from_environment",
        side_effect=ValueError("invalid configuration"),
    ):
        result = run()

    assert result == 1


def test_run_returns_130_for_keyboard_interrupt() -> None:
    settings = _settings()
    crawler = AsyncMock(side_effect=KeyboardInterrupt)

    with (
        patch(
            "docsync.main.Settings.from_environment",
            return_value=settings,
        ),
        patch(
            "docsync.main.configure_logging",
            return_value=MagicMock(),
        ),
        patch(
            "docsync.main.run_crawler",
            crawler,
        ),
    ):
        result = run()

    assert result == 130
    crawler.assert_awaited_once_with(settings.start_url)


def test_main_delegates_to_run() -> None:
    with patch("docsync.main.run", return_value=27) as mocked_run:
        result = main()

    assert result == 27
    mocked_run.assert_called_once_with()


def test_python_module_entrypoint_calls_main() -> None:
    with patch("docsync.cli.main") as mocked_main:
        runpy.run_path(
            str(
                Path(__file__).resolve().parents[1] / "src" / "docsync" / "__main__.py"
            ),
            run_name="__main__",
        )

    mocked_main.assert_called_once_with()
