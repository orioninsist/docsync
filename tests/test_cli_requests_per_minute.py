"""Canonical CLI request-rate option tests."""

from __future__ import annotations

import os

import pytest

from docsync.cli import _apply_environment_overrides, build_parser


def test_cli_help_exposes_requests_per_minute() -> None:
    assert "--requests-per-minute" in build_parser().format_help()


def test_cli_parses_requests_per_minute() -> None:
    arguments = build_parser().parse_args(
        [
            "--requests-per-minute",
            "17",
        ]
    )

    assert arguments.requests_per_minute == 17


def test_cli_requests_per_minute_updates_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "DOCSYNC_REQUESTS_PER_MINUTE",
        raising=False,
    )

    arguments = build_parser().parse_args(
        [
            "--requests-per-minute",
            "17",
        ]
    )

    _apply_environment_overrides(arguments)

    assert os.environ["DOCSYNC_REQUESTS_PER_MINUTE"] == "17"


def test_cli_rejects_non_positive_requests_per_minute() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [
                "--requests-per-minute",
                "0",
            ]
        )


def test_environment_override_accepts_namespace_without_request_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "DOCSYNC_REQUESTS_PER_MINUTE",
        raising=False,
    )

    arguments = build_parser().parse_args([])

    delattr(arguments, "requests_per_minute")

    _apply_environment_overrides(arguments)

    assert "DOCSYNC_REQUESTS_PER_MINUTE" not in os.environ
