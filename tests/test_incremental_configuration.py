"""Package incremental configuration contracts."""

from __future__ import annotations

import inspect

import pytest

from docsync.cli import build_parser
from docsync.config import (
    DEFAULT_REFRESH_HOURS,
    MAX_REFRESH_HOURS,
    Settings,
)
from docsync.crawler import run_crawler


def _clear_incremental_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "DOCSYNC_REFRESH_HOURS",
        raising=False,
    )
    monkeypatch.delenv(
        "DOCSYNC_FORCE_REFRESH",
        raising=False,
    )


def test_settings_exposes_incremental_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_incremental_environment(monkeypatch)

    settings = Settings.from_environment()

    assert settings.refresh_hours == DEFAULT_REFRESH_HOURS
    assert settings.force_refresh is False


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    (
        ("0", 0),
        ("24", 24),
        (str(MAX_REFRESH_HOURS), MAX_REFRESH_HOURS),
    ),
)
def test_refresh_hours_loads_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    raw_value: str,
    expected: int,
) -> None:
    _clear_incremental_environment(monkeypatch)
    monkeypatch.setenv(
        "DOCSYNC_REFRESH_HOURS",
        raw_value,
    )

    settings = Settings.from_environment()

    assert settings.refresh_hours == expected


@pytest.mark.parametrize(
    "raw_value",
    ("1", "true", "TRUE", "yes", "on"),
)
def test_force_refresh_true_environment_values(
    monkeypatch: pytest.MonkeyPatch,
    raw_value: str,
) -> None:
    _clear_incremental_environment(monkeypatch)
    monkeypatch.setenv(
        "DOCSYNC_FORCE_REFRESH",
        raw_value,
    )

    settings = Settings.from_environment()

    assert settings.force_refresh is True


@pytest.mark.parametrize(
    "raw_value",
    ("", "0", "false", "no", "off", "unexpected"),
)
def test_force_refresh_false_environment_values(
    monkeypatch: pytest.MonkeyPatch,
    raw_value: str,
) -> None:
    _clear_incremental_environment(monkeypatch)
    monkeypatch.setenv(
        "DOCSYNC_FORCE_REFRESH",
        raw_value,
    )

    settings = Settings.from_environment()

    assert settings.force_refresh is False


@pytest.mark.parametrize(
    "raw_value",
    ("-1", str(MAX_REFRESH_HOURS + 1)),
)
def test_refresh_hours_rejects_out_of_range_values(
    monkeypatch: pytest.MonkeyPatch,
    raw_value: str,
) -> None:
    _clear_incremental_environment(monkeypatch)
    monkeypatch.setenv(
        "DOCSYNC_REFRESH_HOURS",
        raw_value,
    )

    with pytest.raises(
        ValueError,
        match="refresh_hours",
    ):
        Settings.from_environment()


def test_cli_exposes_incremental_options() -> None:
    parser = build_parser()

    arguments = parser.parse_args(
        [
            "https://example.com/docs",
            "--refresh-hours",
            "48",
            "--force-refresh",
        ]
    )

    assert arguments.refresh_hours == 48
    assert arguments.force_refresh is True


def test_cli_incremental_defaults_remain_unset() -> None:
    parser = build_parser()

    arguments = parser.parse_args(["https://example.com/docs"])

    assert arguments.refresh_hours is None
    assert arguments.force_refresh is None


def test_run_crawler_accepts_incremental_options() -> None:
    parameters = inspect.signature(run_crawler).parameters

    assert "refresh_hours" in parameters
    assert "force_refresh" in parameters
    assert parameters["refresh_hours"].default is None
    assert parameters["force_refresh"].default is None
