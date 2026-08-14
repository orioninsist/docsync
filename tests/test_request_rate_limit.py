"""Deterministic request-rate configuration contracts."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path

import pytest

from docsync.config import (
    DEFAULT_REQUESTS_PER_MINUTE,
    MAX_REQUESTS_PER_MINUTE,
    MIN_REQUESTS_PER_MINUTE,
    Settings,
)
from docsync.crawler_runtime import build_crawlee_runtime

ROOT = Path(__file__).resolve().parents[1]
CRAWLER_PATH = ROOT / "src" / "docsync" / "crawler.py"


def settings_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> Settings:
    monkeypatch.setenv(
        "DOCSYNC_START_URL",
        "https://example.com/docs",
    )
    monkeypatch.setenv(
        "DOCSYNC_OUTPUT_DIR",
        "output",
    )
    monkeypatch.setenv(
        "DOCSYNC_STATE_DIR",
        "storage/docsync",
    )

    return Settings.from_environment()


def run_crawler_node() -> ast.AsyncFunctionDef:
    tree = ast.parse(
        CRAWLER_PATH.read_text(encoding="utf-8"),
        filename=str(CRAWLER_PATH),
    )

    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_crawler"
    ]

    assert len(matches) == 1
    return matches[0]


def crawler_constructor() -> ast.Call:
    matches = [
        node
        for node in ast.walk(run_crawler_node())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "BeautifulSoupCrawler"
    ]

    assert len(matches) == 1
    return matches[0]


def test_rate_limit_constants_are_conservative() -> None:
    assert DEFAULT_REQUESTS_PER_MINUTE == 6
    assert MIN_REQUESTS_PER_MINUTE == 1
    assert MAX_REQUESTS_PER_MINUTE == 60


def test_default_requests_per_minute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "DOCSYNC_REQUESTS_PER_MINUTE",
        raising=False,
    )

    settings = settings_from_environment(monkeypatch)

    assert settings.requests_per_minute == 6


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("1", 1),
        ("6", 6),
        ("30", 30),
        ("60", 60),
    ],
)
def test_valid_requests_per_minute(
    monkeypatch: pytest.MonkeyPatch,
    raw_value: str,
    expected: int,
) -> None:
    monkeypatch.setenv(
        "DOCSYNC_REQUESTS_PER_MINUTE",
        raw_value,
    )

    settings = settings_from_environment(monkeypatch)

    assert settings.requests_per_minute == expected


@pytest.mark.parametrize(
    "raw_value",
    [
        "",
        "0",
        "-1",
        "61",
        "invalid",
        "1.5",
    ],
)
def test_invalid_requests_per_minute(
    monkeypatch: pytest.MonkeyPatch,
    raw_value: str,
) -> None:
    monkeypatch.setenv(
        "DOCSYNC_REQUESTS_PER_MINUTE",
        raw_value,
    )

    with pytest.raises(
        ValueError,
        match="DOCSYNC_REQUESTS_PER_MINUTE",
    ):
        settings_from_environment(monkeypatch)


def test_crawler_wires_max_tasks_per_minute() -> None:
    runtime = asyncio.run(
        build_crawlee_runtime(
            hostname="example.com",
            max_concurrency=2,
            requests_per_minute=20,
            request_timeout_seconds=60,
        )
    )

    assert runtime.concurrency_settings.max_tasks_per_minute == 20


def test_existing_concurrency_controls_are_preserved() -> None:
    runtime = asyncio.run(
        build_crawlee_runtime(
            hostname="example.com",
            max_concurrency=3,
            requests_per_minute=20,
            request_timeout_seconds=60,
        )
    )

    settings = runtime.concurrency_settings

    assert settings.min_concurrency == 1
    assert settings.max_concurrency == 3
    assert settings.desired_concurrency == 3
    assert settings.max_tasks_per_minute == 20


def test_existing_crawler_limits_are_preserved() -> None:
    keyword_names = {keyword.arg for keyword in crawler_constructor().keywords}

    assert {
        "concurrency_settings",
        "max_request_retries",
        "max_requests_per_crawl",
        "request_handler_timeout",
    }.issubset(keyword_names)


def test_crawl_delay_remains_runtime_wired() -> None:
    runtime = asyncio.run(
        build_crawlee_runtime(
            hostname="example.com",
            max_concurrency=2,
            requests_per_minute=20,
            request_timeout_seconds=60,
        )
    )

    assert type(runtime.request_manager).__name__ == "ThrottlingRequestManager"
    assert "example.com" in runtime.request_manager._domain_states
