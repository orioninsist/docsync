"""Browser-mode Settings, CLI, and crawler contracts."""

from __future__ import annotations

import argparse
import ast
import os
from pathlib import Path
from typing import Final

import pytest

from docsync.cli import (
    _apply_environment_overrides,
    _invoke_run_crawler,
    build_parser,
)
from docsync.config import Settings

ROOT: Final[Path] = Path(__file__).resolve().parents[1]
CONFIG_PATH: Final[Path] = ROOT / "src/docsync/config.py"
CLI_PATH: Final[Path] = ROOT / "src/docsync/cli.py"
CRAWLER_PATH: Final[Path] = ROOT / "src/docsync/crawler.py"


def configure_runtime_directories(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv(
        "DOCSYNC_OUTPUT_DIR",
        str(tmp_path / "output"),
    )
    monkeypatch.setenv(
        "DOCSYNC_STATE_DIR",
        str(tmp_path / "state"),
    )
    monkeypatch.setenv(
        "DOCSYNC_LOG_DIR",
        str(tmp_path / "logs"),
    )


def test_settings_default_browser_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_runtime_directories(
        monkeypatch,
        tmp_path,
    )

    monkeypatch.delenv(
        "DOCSYNC_MODE",
        raising=False,
    )
    monkeypatch.delenv(
        "DOCSYNC_HEADLESS",
        raising=False,
    )
    monkeypatch.delenv(
        "DOCSYNC_BROWSER_TYPE",
        raising=False,
    )

    settings = Settings.from_environment()

    assert settings.mode == "http"
    assert settings.headless is True
    assert settings.browser_type == "chromium"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "http",
            "http",
        ),
        (
            "playwright",
            "playwright",
        ),
        (
            "browser",
            "playwright",
        ),
        (
            "javascript",
            "playwright",
        ),
        (
            "js",
            "playwright",
        ),
    ],
)
def test_settings_normalize_mode_aliases(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    value: str,
    expected: str,
) -> None:
    configure_runtime_directories(
        monkeypatch,
        tmp_path,
    )
    monkeypatch.setenv(
        "DOCSYNC_MODE",
        value,
    )

    settings = Settings.from_environment()

    assert settings.mode == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "selenium",
        "dynamic",
    ],
)
def test_settings_reject_invalid_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    value: str,
) -> None:
    configure_runtime_directories(
        monkeypatch,
        tmp_path,
    )
    monkeypatch.setenv(
        "DOCSYNC_MODE",
        value,
    )

    with pytest.raises(
        ValueError,
        match="crawler mode must be",
    ):
        Settings.from_environment()


@pytest.mark.parametrize(
    "value",
    [
        "chromium",
        "firefox",
        "webkit",
    ],
)
def test_settings_accept_browser_engines(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    value: str,
) -> None:
    configure_runtime_directories(
        monkeypatch,
        tmp_path,
    )
    monkeypatch.setenv(
        "DOCSYNC_BROWSER_TYPE",
        value.upper(),
    )

    settings = Settings.from_environment()

    assert settings.browser_type == value


def test_settings_reject_invalid_browser_engine(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    configure_runtime_directories(
        monkeypatch,
        tmp_path,
    )
    monkeypatch.setenv(
        "DOCSYNC_BROWSER_TYPE",
        "opera",
    )

    with pytest.raises(
        ValueError,
        match="browser type must be",
    ):
        Settings.from_environment()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "true",
            True,
        ),
        (
            "1",
            True,
        ),
        (
            "false",
            False,
        ),
        (
            "0",
            False,
        ),
    ],
)
def test_settings_read_headless_boolean(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    value: str,
    expected: bool,
) -> None:
    configure_runtime_directories(
        monkeypatch,
        tmp_path,
    )
    monkeypatch.setenv(
        "DOCSYNC_HEADLESS",
        value,
    )

    settings = Settings.from_environment()

    assert settings.headless is expected


def test_cli_browser_flags() -> None:
    parser = build_parser()

    mode_args = parser.parse_args(
        [
            "https://example.com/docs",
            "--mode",
            "playwright",
        ]
    )
    javascript_args = parser.parse_args(
        [
            "https://example.com/docs",
            "--javascript",
        ]
    )
    browser_args = parser.parse_args(
        [
            "https://example.com/docs",
            "--browser",
        ]
    )
    playwright_args = parser.parse_args(
        [
            "https://example.com/docs",
            "--playwright",
        ]
    )
    visible_args = parser.parse_args(
        [
            "https://example.com/docs",
            "--show-browser",
        ]
    )
    firefox_args = parser.parse_args(
        [
            "https://example.com/docs",
            "--browser-type",
            "firefox",
        ]
    )

    assert mode_args.mode == "playwright"
    assert javascript_args.mode == "playwright"
    assert browser_args.mode == "playwright"
    assert playwright_args.mode == "playwright"
    assert visible_args.headless is False
    assert firefox_args.browser_type == "firefox"


def test_environment_overrides_include_browser_configuration() -> None:
    args = argparse.Namespace(
        start_url="https://example.com/docs",
        output_dir=None,
        state_dir=None,
        max_concurrency=None,
        max_requests=None,
        language=None,
        refresh_hours=None,
        force_refresh=None,
        mode="playwright",
        headless=False,
        browser_type="webkit",
    )

    _apply_environment_overrides(args)

    assert os.environ["DOCSYNC_MODE"] == "playwright"
    assert os.environ["DOCSYNC_HEADLESS"] == "False"
    assert os.environ["DOCSYNC_BROWSER_TYPE"] == "webkit"


def test_invoke_run_crawler_forwards_browser_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_run_crawler(
        start_url: str,
        mode: str | None = None,
        headless: bool | None = None,
        browser_type: str | None = None,
    ) -> None:
        captured.update(
            {
                "start_url": start_url,
                "mode": mode,
                "headless": headless,
                "browser_type": browser_type,
            }
        )

    monkeypatch.setattr(
        "docsync.cli.run_crawler",
        fake_run_crawler,
    )

    args = argparse.Namespace(
        start_url="https://example.com/docs",
        output_dir=None,
        state_dir=None,
        max_concurrency=None,
        max_requests=None,
        language=None,
        refresh_hours=None,
        force_refresh=None,
        mode="playwright",
        headless=False,
        browser_type="firefox",
    )

    _invoke_run_crawler(args)

    assert captured == {
        "start_url": "https://example.com/docs",
        "mode": "playwright",
        "headless": False,
        "browser_type": "firefox",
    }


def test_run_crawler_browser_parameters_and_reporting() -> None:
    source = CRAWLER_PATH.read_text(
        encoding="utf-8",
    )
    tree = ast.parse(
        source,
        filename=str(CRAWLER_PATH),
    )

    run_crawler = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_crawler"
    )

    parameter_names = {argument.arg for argument in run_crawler.args.args}

    assert {
        "mode",
        "headless",
        "browser_type",
    } <= parameter_names

    assert "CrawlStats(mode=resolved_mode)" in source
    assert '"mode": resolved_mode' in source
    assert '"headless": resolved_headless' in source
    assert '"browser_type": resolved_browser_type' in source


def test_playwright_selection_is_wired() -> None:
    source = CRAWLER_PATH.read_text(
        encoding="utf-8",
    )
    tree = ast.parse(
        source,
        filename=str(CRAWLER_PATH),
    )

    run_crawler = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_crawler"
    )

    constructor_names = {
        node.func.id
        for node in ast.walk(run_crawler)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "BeautifulSoupCrawler" in constructor_names
    assert "PlaywrightCrawler" in constructor_names
    assert "PlaywrightRenderingConfig" in constructor_names
    assert "render_page_html" in constructor_names
    assert "install_resource_blocking" in constructor_names

    comparisons = [
        node for node in ast.walk(run_crawler) if isinstance(node, ast.Compare)
    ]

    assert any(
        isinstance(comparison.left, ast.Name)
        and comparison.left.id == "resolved_mode"
        and any(
            isinstance(comparator, ast.Constant) and comparator.value == "playwright"
            for comparator in comparison.comparators
        )
        for comparison in comparisons
    )
